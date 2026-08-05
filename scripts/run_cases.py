from pathlib import Path
import sys


# Make the repository script runnable without requiring an editable install.
# The package itself remains under src/ for normal packaging workflows.
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from olist_multi_agent.main import main


if __name__ == "__main__":
    raise SystemExit(main())
