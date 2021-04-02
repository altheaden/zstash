from __future__ import absolute_import, print_function

import argparse
import logging
import os
import sqlite3
import sys
from typing import List, Tuple

from .hpss import hpss_get
from .settings import (
    DEFAULT_CACHE,
    FilesRow,
    TupleFilesRow,
    config,
    get_db_filename,
    logger,
)
from .utils import update_config


def ls():
    """
    List all of the files in the HPSS path.
    Supports the '-l' argument for more information.
    """

    args: argparse.Namespace
    cache: str
    args, cache = setup_ls()

    matches: List[FilesRow] = ls_database(args, cache)

    # Print the results
    match: FilesRow
    for match in matches:
        if args.long:
            # Print all contents of each match
            for col in match.to_tuple():
                print(col, end="\t")
            print("")
        else:
            # Just print the file name
            print(match.name)


def setup_ls() -> Tuple[argparse.Namespace, str]:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        usage="zstash ls [<args>] [files]",
        description="List the files from an existing archive. If `files` is specified, then only the files specified will be listed. If `hpss=none`, then this will list the directories and files in the current directory excluding the cache.",
    )
    optional: argparse._ArgumentGroup = parser.add_argument_group(
        "optional named arguments"
    )
    optional.add_argument("--hpss", type=str, help="path to HPSS storage")
    optional.add_argument(
        "-l",
        dest="long",
        action="store_const",
        const=True,
        help="show more information for the files",
    )
    optional.add_argument(
        "--cache",
        type=str,
        help='the path to the zstash archive on the local file system. The default name is "zstash".',
    )
    optional.add_argument(
        "-v", "--verbose", action="store_true", help="increase output verbosity"
    )

    parser.add_argument("files", nargs="*", default=["*"])
    args: argparse.Namespace = parser.parse_args(sys.argv[2:])
    if args.hpss and args.hpss.lower() == "none":
        args.hpss = "none"
    cache: str
    if args.cache:
        cache = args.cache
    else:
        cache = DEFAULT_CACHE
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    return args, cache


def ls_database(args: argparse.Namespace, cache: str) -> List[FilesRow]:
    # Open database
    logger.debug("Opening index database")
    if not os.path.exists(get_db_filename(cache)):
        # Will need to retrieve from HPSS
        if args.hpss is not None:
            config.hpss = args.hpss
            if config.hpss is not None:
                hpss = config.hpss
            else:
                raise TypeError("Invalid config.hpss={}".format(config.hpss))
            # Retrieve from HPSS
            hpss_get(hpss, get_db_filename(cache), cache)
        else:
            error_str: str = (
                "--hpss argument is required when local copy of database is unavailable"
            )
            logger.error(error_str)
            raise ValueError(error_str)

    con: sqlite3.Connection = sqlite3.connect(
        get_db_filename(cache), detect_types=sqlite3.PARSE_DECLTYPES
    )
    cur: sqlite3.Cursor = con.cursor()

    update_config(cur)

    if config.maxsize is not None:
        maxsize: int = config.maxsize
    else:
        raise TypeError("Invalid config.maxsize={}".format(config.maxsize))
    config.maxsize = maxsize
    if config.keep is not None:
        keep: bool = config.keep
    else:
        raise TypeError("Invalid config.keep={}".format(config.keep))
    config.keep = keep

    # The command line arg should always have precedence
    if args.hpss is not None:
        config.hpss = args.hpss

    # Start doing actual work
    logger.debug("Running zstash ls")
    logger.debug("HPSS path  : %s" % (config.hpss))

    # Find matching files
    matches_: List[TupleFilesRow] = []
    for args_file in args.files:
        cur.execute(
            u"select * from files where name GLOB ? or tar GLOB ?",
            (args_file, args_file),
        )
        matches_ = matches_ + cur.fetchall()

    # Remove duplicates
    matches_ = list(set(matches_))
    matches: List[FilesRow] = list(map(FilesRow, matches_))

    # Sort by tape and order within tapes (offset)
    matches = sorted(matches, key=lambda t: (t.tar, t.offset))

    if args.long:
        # Get the names of the columns
        cur.execute(u"PRAGMA table_info(files);")
        cols = [str(col_info[1]) for col_info in cur.fetchall()]
        print("\t".join(cols))

    # Close database
    con.commit()
    con.close()

    return matches
