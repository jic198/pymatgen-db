"""
Run derived collection builder.

This should be run from the "mgbuild" shell script in this directory.
See mgbuild and README-builders.md for details.

See the -h option for details on the options.
Can run in two modes, 'merge' for building sandbox+core task collections,
and 'vasp' for building the derived collections.
"""
__author__ = 'Dan Gunter <dkgunter@lbl.gov>'
__date__ = '5/22/13'

# System
import argparse
import imp
import json
import logging
import os
import sys
import time
import traceback
# Third-party
import pymongo
# Builders
# Other local stuff
from matgendb.builders import core
from matgendb.query_engine import QueryEngine

_log = None     # configured in main()

DEFAULT_CONFIG_FILE = "db.json"

# Suffix for merged tasks collection
MERGED_SUFFIX = "merged"

## Exceptions

class BuilderError(Exception):
    pass

class ConfigurationError(BuilderError):
    def __init__(self, where, why):
        Exception.__init__(self, "Failed to load configuration {}: {}".format(where, why))

class BuilderNotFoundError(Exception):
    pass

## Build functions


def build_sandbox(args):
    """Merge tasks from a sandbox and core db.
    """
    # Check args.
    if not args.sandbox_file:
        raise ConfigurationError("In sandbox mode, -s/--sandbox is required")

    # Connect to "core" collections.
    try:
        settings = get_settings(args.config_file)
    except ConfigurationError, err:
        p.error(str(err))
    core_db = QueryEngine(**settings)
    if hasattr(args, 'merged_tasks') and args.merged_tasks:
        suffix = MERGED_SUFFIX
    else:
        suffix = None
    core_collections = core.Collections(core_db, task_suffix=suffix)

    # Setup.
    sandbox_settings = get_settings(args.sandbox_file)
    sandbox_db = QueryEngine(**sandbox_settings)
    sdb = sandbox_settings['database']
    pfx = args.coll_prefix
    sandbox_collections = core.Collections(sandbox_db, prefix=pfx)
    # set task id prefix
    if args.sandbox_name:
        id_prefix = args.sandbox_name
    elif pfx:
        id_prefix = pfx
    else:
        id_prefix = "sandbox"
    # set target collection name
    if pfx:
        target = "{}.tasks.{}".format(pfx, MERGED_SUFFIX)
    else:
        target = "tasks.{}".format(MERGED_SUFFIX)

    # Perform the merge.
    _log.debug("sandbox.merge.begin: sandbox={}".format(sdb))
    t0 = time.time()
    try:
        core.merge_tasks(core_collections, sandbox_collections, id_prefix, target, wipe=args.wipe_target)
    except pymongo.errors.DuplicateKeyError, err:
        _log.error("sandbox.merge.end error=merge.duplicate_key msg={}".format(err))
        tell_user("\nDuplicate key error from MongoDB.\nUse -W/--wipe to clear target collection before merge.\n")
        return -1
    _log.debug("sandbox.merge.end: sandbox={} duration_sec={:g}".format(sdb, time.time() - t0))
    tell_user("Merged tasks: db={} collection={}".format(sdb, target))

    return 0


def build_other(args, sub=None, params=None, builder_class=None, db_settings=None):
    """Build using a class discovered at runtime.
    """
    _log.debug("Run plug-in builder <{}> with params: ".format(sub, params))
    # Build up arguments to constructor
    kwargs = {}
    for name, info in params.iteritems():
        value = getattr(args, "{}_{}".format(sub, name))
        # take special action for some types
        if is_mqe(info['type']):  # QueryEngin
            # connect to DB as configured
            db_settings['collection'] = value
            # replace value with MQE obj
            value = QueryEngine(**db_settings)

        kwargs[name] = value
    # Create builder class
    _log.debug("Create builder with kwargs: {}".format(kwargs))
    bld = builder_class(**kwargs)
    # Run builder
    status = bld.run()
    return status


## -- util --

def tell_user(message):
    "Flexible way to control output for the user."
    print(message)


def get_settings(config_file):
    """Read settings from a configuration file.
    """
    try:
        if config_file:
            return json.load(open(config_file))
        elif os.path.exists(DEFAULT_CONFIG_FILE):
            return json.load(open(DEFAULT_CONFIG_FILE))
        else:
            raise ValueError("Default configuration '{}' not found".format(DEFAULT_CONFIG_FILE))
    except Exception, err:
        raise ConfigurationError(config_file, err)


def is_mqe(type_name):
    """Whether this type name is a QueryEngine.
    """
    return type_name.endswith("QueryEngine")


def load_module(module):
    """Extend imp to handle dotted module paths.
    """
    parts = module.split('.')
    path, m = None, None
    # navigate packages
    for p in parts[:-1]:
        loc = imp.find_module(p, path)
        m = imp.load_module(p, *loc)
        path = m.__path__
    # load module
    p = parts[-1]
    loc = imp.find_module(p, path)
    return imp.load_module(p, *loc)


def get_builder(module):
    """Get the (first) Builder subclass found in the module.
    """
    result = None
    moduleobj = load_module(module)
    for name in dir(moduleobj):
        obj = getattr(moduleobj, name)
        #_log.debug("examine {}.{}".format(module, name))
        try:
            if issubclass(obj, core.Builder) and not obj == core.Builder:
                _log.debug("{}.{} is a Builder".format(module, name))
                result = obj
                break
        except TypeError:
            pass
    return result


def list_builders(args):
    """List all the builders in a given module dir.

    :return: Number of builders shown
    """
    # Load parent module.
    module = load_module(args.mod_path)
    # Get all Python modules in directory.
    path = os.path.dirname(module.__file__)
    pyfiles = [f for f in os.listdir(path) if f.endswith('.py') and not f.startswith('__')]
    # Convert back to full module paths.
    pymods = ["{}.{}".format(args.mod_path, os.path.splitext(f)[0]) for f in pyfiles]
    # Find and show builders in the module paths.
    builders = filter(None, [get_builder(m) for m in pymods])
    n = len(builders)
    if n > 0:
        print("Found {:d} builder{}:".format(n, 's' if n > 1 else ''))
        map(show_builder, builders)
    else:
        print("No builders found in module {}".format(args.mod_path))
    return n


def show_builder(b):
    """Print a formatted version of builder info to the console.
    """
    indent = " " * 4
    modname = b.__module__.split(".")[-1]
    print("{i}Module: {m}".format(i=indent, m=modname))
    print("{i}{name}: {desc}".format(i=indent, name=b.__name__, desc=b.__doc__.strip()))
    params = {}
    setup_doc = b.setup.__doc__.split("\n")
    for line in setup_doc:
        s = line.strip()
        if s.startswith(":"):
            words = s.split()
            param_name = words[1].split(":")[0]
            param_desc = ' '.join(words[2:])
            if s.startswith(":param"):
                params[param_name] = [param_desc, None]  # desc goes first
            else:
                params[param_name][1] = param_desc  # type goes second
    print("{i}{i}Keywords:".format(i=indent))
    for key, value in params.iteritems():
        desc, type_ = value
        print("{i}{i}{i}{name} = ({type}) {desc}".format(i=indent, name=key, type=type_,
                                                    desc=desc))


def run_builder(args):
    """Run builder, invoked from 'build' sub-command
    """
    # Get builder in module.
    full_mod_path = "{}.{}".format(args.mod_path, args.builder)
    builder_class = get_builder(full_mod_path)
    if builder_class is None:
        raise BuilderNotFoundError("{}".format(full_mod_path))

    # Get keywords from args.
    args_kw = {}
    for kwd in args.keywords:
        try:
            key, value = kwd.split('=', 1)
        except ValueError:
            raise ValueError("Bad key=value pair: {}".format(kwd))
        args_kw[key] = value

    # Get database settings and connect.
    _log.info("load DB configuration from '{}'".format(args.config_file))
    db_settings = get_settings(args.config_file)
    builder_db_settings = db_settings.copy()  # keep orig. settings for builder_class.__init__()

    # Normalize user/password from readonly and admin prefixes.
    for pfx in 'readonly', 'admin':  # in reverse order of priority, to overwrite
        if (pfx + '_user') in db_settings and (pfx + '_password') in db_settings:
            builder_db_settings['user'] = builder_db_settings[pfx + '_user']
            builder_db_settings['password'] = builder_db_settings[pfx + '_password']
            del builder_db_settings[pfx + '_user']
            del builder_db_settings[pfx + '_password']

    # Parse builder's setup() method docstring.
    _log.debug("parse builder docstring")
    params, returnval = core.parse_fn_docstring(builder_class.setup)
    for name, info in params.iteritems():
        try:
            value = args_kw[name]
        except KeyError:
            raise ValueError("Key '{}' not found in {}.setup()"
                             .format(name, full_mod_path))
        # take special action for some types
        if is_mqe(info['type']):  # QueryEngine
            # connect to DB as configured
            builder_db_settings['collection'] = value
            # replace value with MQE obj
            try:
                args_kw[name] = QueryEngine(**builder_db_settings)
            except pymongo.errors.ConnectionFailure as err:
                raise BuilderError("Cannot connect from settings in '{}': {}"
                                   .format(args.config_file, err))
            _log.info("Configured query engine {}: {}".format(name, builder_db_settings))

    # Run builder.
    _log.info("run builder")
    builder = builder_class(ncores=args.num_cores, config=db_settings)
    count = builder.run(setup_kw=args_kw)
    if count < 1:
        _log.warn("Processed {:d} items".format(count))
    else:
        _log.info("Processed {:d} items".format(count))
    result = 0

    return result

## -- MAIN --

def main():
    global _log

    # Configure parent parser for shared args.
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('--verbose', '-v', dest='vb', action="count", default=0,
                               help="Print more verbose messages to standard error. Repeatable. (default=ERROR)")
    # Set up argument parsing.
    p = argparse.ArgumentParser(description="Build databases")
    subparsers = p.add_subparsers(description="Actions")

    # Merge action.
    subp = subparsers.add_parser("merge", help="Merge sandbox and core database",
                                 parents=[parent_parser])
    subp.set_defaults(func=build_sandbox)
    subp.add_argument("-c", "--config", dest="config_file", type=str, metavar='FILE', default="db.json",
                      help="Configure database connection from FILE (%(default)s)")
    subp.add_argument("-n", "--name", dest="sandbox_name", type=str, metavar="NAME", default=None,
                      help="Sandbox name, for prefixing merged task IDs. "
                           "If not given, try to use -p/--prefix, then default (sandbox)")
    subp.add_argument("-p", "--prefix", dest="coll_prefix", type=str, metavar='PREFIX', default=None,
                      help="Collection name prefix for input (and possibly output) collections")
    subp.add_argument("-s", "--sandbox", dest="sandbox_file", type=str, metavar='FILE', default=None,
                      help="Configure sandbox database from FILE (required)")
    subp.add_argument("-W", "--wipe", dest="wipe_target", action="store_true",
                      help="Wipe target collection, removing all data in it, before merge")

    # List builders action.
    subp = subparsers.add_parser("list", help="list builders",
                                 parents=[parent_parser])
    subp.set_defaults(func=list_builders)
    subp.add_argument("-m", "--module", dest="mod_path", type=str, metavar="MODULE",
                      default="matgendb.builders",
                      help="Find builder modules under MODULE (default=matgendb.builders)")

    # Build action.
    subp = subparsers.add_parser("build", help="run a builder",
                                 parents=[parent_parser])
    subp.set_defaults(func=run_builder)
    subp.add_argument("-b", "--builder", dest="builder", type=str, metavar="NAME", default="",
                      help="Run builder NAME, which is relative to the module path in -m/--module")
    subp.add_argument("-c", "--config", dest="config_file", type=str, metavar='FILE', default="db.json",
                      help="Configure database connection from FILE (%(default)s)")
    subp.add_argument("-k", "--kvp", dest="keywords", action="append", default=[],
                      help="Key/value pairs, in format <key>=<value>, passed to builder function")
    subp.add_argument("-m", "--module", dest="mod_path", type=str, metavar="MODULE",
                      default="matgendb.builders",
                      help="Find builder modules under MODULE (default=matgendb.builders)")
    subp.add_argument("-n", "--ncores", dest="num_cores", type=int, default=16,
                      help="Number of cores or processes to run in parallel (%(default)d)")
    subp.add_argument("-p", "--prefix", dest="coll_prefix", type=str, metavar='PREFIX', default=None,
                      help="Collection name prefix for input (and possibly output) collections")
    # Parse arguments.
    args = p.parse_args()

    # Configure logging.
    _log = logging.getLogger("mg")  # parent
    _log.propagate = False
    hndlr = logging.StreamHandler()
    hndlr.setFormatter(logging.Formatter("[%(levelname)-6s] %(asctime)s %(name)s :: %(message)s"))
    _log.addHandler(hndlr)
    if args.vb > 1:
        lvl = logging.DEBUG
    elif args.vb > 0:
        lvl = logging.INFO
    else:
        lvl = logging.WARN
    _log.setLevel(lvl)
    _log = logging.getLogger("mg.build")
    # don't send logs up

    # Run function.
    if args.func is None:
        p.error("No action given")
    try:
        result = args.func(args)
    except ConfigurationError as err:
        _log.error("Configuration error: {}".format(err))
        result = -1
    except BuilderNotFoundError as err:
        _log.error("Builder not found: {}".format(err))
        result = -1
    except BuilderError as err:
        _log.error("{}".format(err))
        result = -1
    except Exception as err:
        if _log.getEffectiveLevel() <= logging.INFO:
            print("{}".format(traceback.format_exc()))
        p.error("{} error: {}".format(args.func.__name__, err))
        result = -2
    if result < 0:
        _log.error("Failure: {:d}".format(result))
    return result

if __name__ == '__main__':
    sys.exit(main())