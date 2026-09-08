"""greenlint — static analysis for energy-wasteful patterns.

Rules are regex+context based and language-tagged; the rule set is the
product and grows over time. Every finding explains *why it wastes energy*
and what to do instead.

  greenlint src/
  greenlint --list-rules
  greenlint src/ --format json --fail-on-findings
  greenlint . --exclude '*/vendor/*' --exclude '*/dist/*'
"""

from .astindex import SCOPE_BOUNDARIES as SCOPE_BOUNDARIES
from .astindex import Collector as Collector
from .astindex import Loops as Loops
from .astindex import PythonIndex as PythonIndex
from .astindex import _parse_python as _parse_python
from .astindex import index_python as index_python
from .base import BASELINE_FILENAME as BASELINE_FILENAME
from .base import CONFIG_FILENAME as CONFIG_FILENAME
from .base import Config as Config
from .base import Finding as Finding
from .base import Matcher as Matcher
from .base import Rule as Rule
from .baselines import SEVERITY_ORDER as SEVERITY_ORDER
from .baselines import applicable as applicable
from .baselines import apply_baseline as apply_baseline
from .baselines import finding_sort_key as finding_sort_key
from .baselines import fingerprint as fingerprint
from .baselines import load_baseline as load_baseline
from .baselines import write_baseline as write_baseline
from .carbon import BUSY_CORE_WATTS as BUSY_CORE_WATTS
from .carbon import CO2E_HINTS as CO2E_HINTS
from .carbon import G_CO2E_PER_GB as G_CO2E_PER_GB
from .carbon import GRID_INTENSITY_G_PER_KWH as GRID_INTENSITY_G_PER_KWH
from .carbon import KWH_PER_GB_TRANSFERRED as KWH_PER_GB_TRANSFERRED
from .carbon import PAIR as PAIR
from .carbon import core_seconds_per_gram as core_seconds_per_gram
from .cli import main as main
from .comments import COMMENT_SYNTAX as COMMENT_SYNTAX
from .comments import _blank_comments as _blank_comments
from .comments import _blank_spans as _blank_spans
from .comments import _blank_strings as _blank_strings
from .config import load_config as load_config
from .discovery import PRUNED_DIR_NAMES as PRUNED_DIR_NAMES
from .discovery import _ignore_matcher as _ignore_matcher
from .discovery import _matches_any as _matches_any
from .discovery import is_ignored as is_ignored
from .discovery import iter_files as iter_files
from .discovery import prunable_bases as prunable_bases
from .discovery import scan as scan
from .discovery import walk_files as walk_files
from .findings import TEST_FILENAME as TEST_FILENAME
from .infra import NEEDS_FULL_HISTORY as NEEDS_FULL_HISTORY
from .pyrules import NUMERIC_ONLY_OPS as NUMERIC_ONLY_OPS
from .pyrules import PROBE_CALLS as PROBE_CALLS
from .pyrules import SCALAR_CALLS as SCALAR_CALLS
from .pyrules import SCALAR_OPS as SCALAR_OPS
from .rules import AST_RULE_IDS as AST_RULE_IDS
from .rules import PATTERN_RULES_BY_LANG as PATTERN_RULES_BY_LANG
from .rules import RULES as RULES
from .rules import RULES_BY_ID as RULES_BY_ID
from .rules import SCANNABLE_LANGS as SCANNABLE_LANGS
from .scanning import AST_FINDERS as AST_FINDERS
from .scanning import BLOCK_FINDERS as BLOCK_FINDERS
from .scanning import scan_file as scan_file
from .scanning import scannable as scannable

__all__ = [
    "AST_FINDERS",
    "AST_RULE_IDS",
    "BASELINE_FILENAME",
    "BLOCK_FINDERS",
    "BUSY_CORE_WATTS",
    "CO2E_HINTS",
    "COMMENT_SYNTAX",
    "CONFIG_FILENAME",
    "GRID_INTENSITY_G_PER_KWH",
    "G_CO2E_PER_GB",
    "KWH_PER_GB_TRANSFERRED",
    "NEEDS_FULL_HISTORY",
    "NUMERIC_ONLY_OPS",
    "PAIR",
    "PATTERN_RULES_BY_LANG",
    "PROBE_CALLS",
    "PRUNED_DIR_NAMES",
    "RULES",
    "RULES_BY_ID",
    "SCALAR_CALLS",
    "SCALAR_OPS",
    "SCANNABLE_LANGS",
    "SCOPE_BOUNDARIES",
    "SEVERITY_ORDER",
    "TEST_FILENAME",
    "Collector",
    "Config",
    "Finding",
    "Loops",
    "Matcher",
    "PythonIndex",
    "Rule",
    "_blank_comments",
    "_blank_spans",
    "_blank_strings",
    "_ignore_matcher",
    "_matches_any",
    "_parse_python",
    "applicable",
    "apply_baseline",
    "core_seconds_per_gram",
    "finding_sort_key",
    "fingerprint",
    "index_python",
    "is_ignored",
    "iter_files",
    "load_baseline",
    "load_config",
    "main",
    "prunable_bases",
    "scan",
    "scan_file",
    "scannable",
    "walk_files",
    "write_baseline",
]
