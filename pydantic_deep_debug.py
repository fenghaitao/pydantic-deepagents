
import sys
# sys.path.insert(0, 'pydantic-deepagents')
from apps.cli.main import app

sys.argv = [sys.argv[0],
            # 'spec', 'index', '--project-name', 'hwrs', '-P', 'hwrs/HWRS_MAS-dmr.md', '--local',
            'spec', 'diff', '-n', 'hwrs-cor', '-n', 'hwrs-dmr'
            ]

app()