import argparse
import copy
import sys
import os
import traceback
import yaml

from menu_tools.rate_table.menu_table import MenuTable
from menu_tools.rate_table import typst_table
from menu_tools.utils.versions import (
    add_version_argument,
    get_versions,
    parse_args,
    run_per_version,
)


def _extract_version(path: str) -> str:
    parts = path.split(os.sep)
    try:
        idx = parts.index("configs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return "unknown_version"


def main():
    # ensure log printouts are flushed per line for easier monitoring when output is piped, e.g via tee
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config_file",
        help="Path to the menu config file, e.g. `configs/V29/rate_table/v29_cfg.yml`",
        default="configs/V38nano/rate_table/v38_cfg.yml",
    )
    add_version_argument(parser)
    parser.add_argument(
        "--scalings",
        type=str,
        help=(
            "Override version the online-to-offline scalings are loaded from. "
            "Takes precedence over --version for the scalings only; output "
            "filenames get a `_scalings_<version>` suffix."
        ),
        default=None,
    )
    parser.add_argument(
        "--signal",
        type=str,
        help=(
            "Override the sample from the config with a signal sample, to get "
            "per-seed signal efficiencies instead of rates. The rate column is "
            "dropped and output filenames get a `_<sample>` suffix."
        ),
        default=None,
    )
    parser.add_argument(
        "--truncated",
        action="store_true",
        help=(
            "Round the scalings to two decimals, as in the P2GT emulator menus, "
            "so that both apply identical thresholds. Output filenames get a "
            "`_truncated` suffix."
        ),
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=int(os.environ.get("MENU_TABLE_JOBS", "1")),
        help=(
            "Number of seeds to evaluate in parallel, one forked process per "
            "seed (the loaded objects are shared copy-on-write). 0 uses all "
            "cores. Default 1 (serial). Each worker holds its own chunk-sized "
            "buffers, so keep MENU_TABLE_CHUNK in mind on small machines."
        ),
    )
    args = parse_args(parser)

    with open(args.config_file, "r") as f:
        menu_config_dict = yaml.safe_load(f)

    config_version = _extract_version(args.config_file)

    def run(version):
        menu_table = MenuTable(
            copy.deepcopy(menu_config_dict),  # each version starts from the config as read
            config_version=config_version,
            override_version=version,
            override_scalings_version=args.scalings,
            override_sample=args.signal,
            truncated=args.truncated,
            jobs=args.jobs,
        )
        menu_table.make_table()
        menu_table.print_table()
        csv_path = menu_table.save_table()
        menu_table.dump_masks()

        if not menu_table.config.is_signal:
            # The Typst menu table rides along with every rate CSV. A failure
            # here must not lose an expensive rate run, hence the warning.
            try:
                typst_table.write_typst_table(
                    copy.deepcopy(menu_config_dict), menu_table.config, csv_path
                )
            except Exception as exc:
                print(f"WARNING: could not write the Typst menu table: {exc}")
                traceback.print_exc()

    run_per_version(get_versions(parser, args), run)

    # menu_table.compute_tot_and_pure()


if __name__ == "__main__":
    main()
