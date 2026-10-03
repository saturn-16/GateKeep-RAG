param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'test', 'lint', 'seed', 'demo', 'run', 'real-test', 'help')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$Python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }

switch ($Task) {
    'up' { docker compose up --build -d; break }
    'down' { docker compose down; break }
    'test' { & $Python -m pytest -q; break }
    'lint' { & $Python -m compileall -q src tests scripts eval alembic; break }
    'seed' { $env:PYTHONPATH = 'src'; $env:PERSISTENCE_BACKEND = 'postgres'; $env:VECTOR_BACKEND = 'qdrant'; & $Python scripts/seed_demo.py; break }
    'demo' { $env:PYTHONPATH = 'src'; & $Python scripts/attack_demo.py; break }
    'run' { $env:PYTHONPATH = 'src'; & $Python -m uvicorn app.main:app --reload; break }
    'real-test' {
        $env:PYTHONPATH = 'src'
        $env:RUN_REAL_STACK = '1'
        $env:PERSISTENCE_BACKEND = 'postgres'
        $env:VECTOR_BACKEND = 'qdrant'
        & $Python -m pytest -q tests/integration/
        break
    }
    default {
        Write-Output 'Usage: .\tasks.ps1 <up|down|test|lint|seed|demo|run|real-test>'
    }
}
