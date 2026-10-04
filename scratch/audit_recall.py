import re
import string
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("src"))
sys.path.insert(0, os.path.abspath("."))

from app.config import get_settings
from app.rag.vectorstore.qdrant_store import QdrantVectorStore
from app.core.principal import Principal
from scripts.run_eval import EVAL_DOC_TEMPLATES, HANDWRITTEN_DEV_QUERIES, HANDWRITTEN_TEST_QUERIES

ORIGINAL_30_QUERIES = [
    # HR & Employee Care
    ("employee-handbook-leave", "How much paid vacation and sick leave do new employees receive each year?", {"employee", "hr", "admin"}, "internal"),
    ("employee-handbook", "What kind of medical, dental, and health coverage is provided by the company?", {"employee", "hr", "admin"}, "internal"),
    ("employee-handbook", "Where can I read about our workplace code of conduct and ethics policy?", {"employee", "hr", "admin"}, "internal"),
    ("performance-review-guidelines", "When and how do our annual performance evaluation reviews take place?", {"employee", "hr", "admin"}, "internal"),
    ("performance-review-guidelines", "Can team members submit anonymous peer 360 feedback before reviews?", {"employee", "hr", "admin"}, "internal"),
    ("salary-bands-2026", "How much base pay do staff software engineers make according to the salary guidelines?", {"hr", "admin"}, "restricted"),
    ("salary-bands-2026", "What is the bonus and commission structure for enterprise sales reps?", {"hr", "admin"}, "restricted"),
    ("executive-compensation-retention", "What happens to stock options if the company gets acquired or changes control?", {"hr", "admin"}, "restricted"),
    ("executive-compensation-retention", "What is the standard severance payout for departing senior executives?", {"hr", "admin"}, "restricted"),
    # Finance & Budgeting
    ("quarterly-financial-forecast", "What are the projected profit margins and revenue growth expectations for this quarter?", {"finance", "admin"}, "confidential"),
    ("quarterly-financial-forecast", "How much money has been budgeted for expanding our cloud infrastructure and server clusters?", {"finance", "admin"}, "confidential"),
    ("annual-budget-allocation", "What is the deadline for submitting corporate tax filings and revenue statements?", {"finance", "admin"}, "confidential"),
    ("annual-budget-allocation", "How many new engineering roles are approved for hiring in the upcoming fiscal year?", {"finance", "admin"}, "confidential"),
    # Engineering & Security
    ("disaster-recovery-protocol", "What is the maximum allowed downtime before our disaster recovery systems must be back online?", {"engineering", "admin"}, "confidential"),
    ("disaster-recovery-protocol", "How frequently are offsite data backups replicated to secondary regions?", {"engineering", "admin"}, "confidential"),
    ("incident-response-playbook", "What are the mandatory security steps for handling an ongoing data breach or intrusion?", {"engineering", "admin"}, "confidential"),
    ("incident-response-playbook", "How often are developers required to rotate API keys and database credentials?", {"engineering", "admin"}, "confidential"),
    ("architecture-standards", "What are our architectural requirements for encrypting data while in transit and at rest?", {"engineering", "admin"}, "confidential"),
    ("architecture-standards", "Which programming languages and microservice frameworks are recommended for new backend services?", {"engineering", "admin"}, "confidential"),
    # Legal, Compliance & Privacy
    ("corporate-legal-nda", "Does the company own patents and intellectual property invented by engineers on company time?", {"admin"}, "restricted"),
    ("corporate-legal-nda", "How long do confidentiality restrictions remain in effect after an agreement ends?", {"admin"}, "restricted"),
    ("vendor-contract-terms", "What are the uptime service level agreement requirements for our third-party software vendors?", {"legal", "finance", "admin"}, "confidential"),
    ("customer-privacy-gdpr", "What is the official procedure for processing customer GDPR data deletion requests?", {"legal", "admin"}, "confidential"),
    ("mergers-acquisitions-strategy", "What criteria do we use when evaluating early-stage AI startups for potential corporate buyout?", {"admin"}, "restricted"),
    ("mergers-acquisitions-strategy", "How do technical and financial due diligence teams audit target liabilities before an acquisition?", {"admin"}, "restricted"),
    # Operations, Marketing, Product & Sales
    ("office-security-policy", "What are the standard working hours and badge access rules for physical office buildings?", {"employee", "admin"}, "internal"),
    ("travel-expense-policy", "How do employees submit reimbursement requests for business travel and client dinners?", {"employee", "finance", "admin"}, "internal"),
    ("brand-marketing-guidelines", "What is the required approval workflow before publishing articles on the public engineering blog?", {"employee", "admin"}, "internal"),
    ("product-launch-playbook", "What metrics and KPIs are tracked during the beta rollout of a new software product feature?", {"engineering", "admin"}, "internal"),
    ("sales-discount-matrix", "Who has permission to grant enterprise customers discounted annual pricing tiers?", {"sales", "finance", "admin"}, "confidential"),
]

STOP_WORDS = {
    "a", "an", "the", "in", "on", "of", "to", "for", "with", "and", "or", "is", "are", "was",
    "were", "be", "been", "by", "what", "which", "how", "when", "where", "who", "whom", "why",
    "our", "their", "do", "does", "did", "can", "could", "should", "would", "must", "have", "has",
    "had", "it", "its", "that", "this", "these", "those", "as", "at", "from", "before", "after"
}

def tokenize(text: str) -> list[str]:
    clean = text.lower().translate(str.maketrans("", "", string.punctuation))
    return clean.split()

def content_words(tokens: list[str]) -> set[str]:
    return {w for w in tokens if w not in STOP_WORDS and len(w) > 1}

def longest_common_ngram(s1_tokens: list[str], s2_tokens: list[str]) -> tuple[int, list[str]]:
    best_len = 0
    best_ngram = []
    s2_set = set()
    for l in range(1, len(s1_tokens) + 1):
        found_any = False
        for i in range(len(s1_tokens) - l + 1):
            ngram = tuple(s1_tokens[i:i+l])
            # check if ngram in s2
            for j in range(len(s2_tokens) - l + 1):
                if tuple(s2_tokens[j:j+l]) == ngram:
                    found_any = True
                    if l > best_len:
                        best_len = l
                        best_ngram = list(ngram)
                    break
        if not found_any:
            break
    return best_len, best_ngram

def main():
    settings = get_settings()
    vector_store = QdrantVectorStore(settings)

    # Map templates
    template_chunks = {}
    for doc_slug, title, allowed_roles, sensitivity, chunks, is_restricted, _ in EVAL_DOC_TEMPLATES:
        template_chunks[doc_slug] = " ".join(c[1] for c in chunks)

    print("=" * 80)
    print("1. AUDIT OF ORIGINAL 30 HAND-WRITTEN QUERIES (FROM MAIN)")
    print("=" * 80)
    print(f"Total queries in original set: {len(ORIGINAL_30_QUERIES)}")
    existing_slugs = set(template_chunks.keys())

    missing_slugs = []
    for slug, q, roles, sens in ORIGINAL_30_QUERIES:
        if slug not in existing_slugs:
            missing_slugs.append((slug, q))
    print(f"Queries with NON-EXISTENT target slugs: {len(missing_slugs)} / {len(ORIGINAL_30_QUERIES)}")
    for slug, q in missing_slugs:
        print(f"  - Non-existent slug '{slug}': '{q}'")

    # Evaluate live retrieval on original 30 queries
    # Using an admin principal with unrestricted clearance to test raw retriever ranking
    admin_principal = Principal("alice", "acme-corp", frozenset({"admin", "hr", "finance", "engineering", "legal", "sales"}), "restricted")

    hits_at_5_raw = 0
    reciprocal_ranks_raw = []

    # Map missing slugs to their intended actual documents
    slug_fix_map = {
        "employee-handbook-leave": "employee-handbook",
        "incident-response-playbook": "incident-response-alpha",
        "architecture-standards": "engineering-architecture",
        "office-security-policy": "office-facilities-guide",
        # Note: brand-marketing-guidelines, product-launch-playbook, sales-discount-matrix do NOT exist in the 210-chunk corpus
    }

    hits_at_5_fixed = 0
    reciprocal_ranks_fixed = []
    applicable_fixed_count = 0

    print("\n--- Live Retrieval Ranking for Original 30 Queries ---")
    for idx, (orig_slug, q_text, roles, sens) in enumerate(ORIGINAL_30_QUERIES, 1):
        target_doc_id_raw = f"acme-corp:{orig_slug}"
        results = vector_store.search(admin_principal, q_text, top_k=5)
        retrieved_doc_ids = [r.doc_id for r in results]

        # Raw evaluation (with original slugs from main)
        hit_raw = target_doc_id_raw in retrieved_doc_ids
        rank_raw = (retrieved_doc_ids.index(target_doc_id_raw) + 1) if hit_raw else None
        if hit_raw:
            hits_at_5_raw += 1
            reciprocal_ranks_raw.append(1.0 / rank_raw)
        else:
            reciprocal_ranks_raw.append(0.0)

        # Fixed slug evaluation (where possible)
        fixed_slug = slug_fix_map.get(orig_slug, orig_slug)
        if fixed_slug in existing_slugs:
            applicable_fixed_count += 1
            target_doc_id_fixed = f"acme-corp:{fixed_slug}"
            hit_fixed = target_doc_id_fixed in retrieved_doc_ids
            rank_fixed = (retrieved_doc_ids.index(target_doc_id_fixed) + 1) if hit_fixed else None
            if hit_fixed:
                hits_at_5_fixed += 1
                reciprocal_ranks_fixed.append(1.0 / rank_fixed)
            else:
                reciprocal_ranks_fixed.append(0.0)
            status_fixed = f"Rank {rank_fixed}" if hit_fixed else "MISS"
        else:
            status_fixed = "N/A (doc absent from corpus)"

        status_raw = f"Rank {rank_raw}" if hit_raw else "MISS"
        print(f"[{idx:02d}] Raw Slug: {orig_slug:<32} | Raw: {status_raw:<7} | Fixed ({fixed_slug}): {status_fixed}")

    recall_5_raw = (hits_at_5_raw / len(ORIGINAL_30_QUERIES)) * 100.0
    mrr_raw = sum(reciprocal_ranks_raw) / len(reciprocal_ranks_raw)
    print("\n" + "=" * 80)
    print("ORIGINAL 30 QUERIES SCORECARD (ON LIVE CORPUS):")
    print(f"  Raw Recall@5 (as written in main) : {recall_5_raw:.2f}% ({hits_at_5_raw}/{len(ORIGINAL_30_QUERIES)})")
    print(f"  Raw MRR (as written in main)      : {mrr_raw:.4f}")
    if applicable_fixed_count:
        recall_5_fixed = (hits_at_5_fixed / applicable_fixed_count) * 100.0
        mrr_fixed = sum(reciprocal_ranks_fixed) / len(reciprocal_ranks_fixed)
        print(f"  Slug-Corrected Recall@5 (27 docs) : {recall_5_fixed:.2f}% ({hits_at_5_fixed}/{applicable_fixed_count})")
        print(f"  Slug-Corrected MRR (27 docs)      : {mrr_fixed:.4f}")
    print("=" * 80)

    all_hw = [("dev", q[0], q[1]) for q in HANDWRITTEN_DEV_QUERIES] + [("test", q[0], q[1]) for q in HANDWRITTEN_TEST_QUERIES]
    high_overlap = []
    
    print(f"{'Split':<5} | {'Doc Slug':<30} | {'Query Content':<14} | {'Chunk Match':<12} | {'Ratio':<8} | {'Longest N-gram'}")
    print("-" * 105)

    for split, slug, query_text in all_hw:
        target_text = template_chunks.get(slug, "")
        q_tokens = tokenize(query_text)
        t_tokens = tokenize(target_text)
        q_content = content_words(q_tokens)
        t_content = content_words(t_tokens)

        shared = q_content & t_content
        ratio = (len(shared) / len(q_content)) if q_content else 0.0
        n_len, n_gram = longest_common_ngram(q_tokens, t_tokens)

        is_flagged = ratio >= 0.50 or n_len >= 4
        if is_flagged:
            high_overlap.append((split, slug, query_text, ratio, n_len, " ".join(n_gram)))

        n_gram_str = f"{n_len}-gram: '{' '.join(n_gram)}'" if n_len >= 3 else f"{n_len}-gram"
        flag = " [FLAGGED]" if is_flagged else ""
        print(f"{split:<5} | {slug:<30} | {len(q_content):<14} | {len(shared):<12} | {ratio*100:>6.1f}% | {n_gram_str}{flag}")

    print("\n" + "=" * 80)
    print(f"SUMMARY OF HIGH LEXICAL OVERLAP QUERIES (Ratio >= 50% OR Longest N-gram >= 4): {len(high_overlap)} / {len(all_hw)}")
    print("=" * 80)
    for split, slug, q, ratio, n_len, ngram_str in high_overlap:
        print(f"[{split.upper()}] Slug: {slug}")
        print(f"  Query        : {q}")
        print(f"  Overlap Ratio: {ratio*100:.1f}%")
        print(f"  Shared N-gram: {n_len}-gram ('{ngram_str}')")

if __name__ == "__main__":
    main()
