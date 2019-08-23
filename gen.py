import argparse
import os
import re
import shutil
import sys

from solidity_parser import parser
from zero_ex.dev_utils import abi_utils


# https://stackoverflow.com/a/41510011
def camel_case_split(identifier):
    RE_WORDS = re.compile(
        r"""
        # Find words in a string. Order matters!
        [A-Z]+(?=[A-Z][a-z]) |  # All upper case before a capitalized word
        [A-Z]?[a-z]+ |  # Capitalized words / all lower case
        [A-Z]+ |  # All upper case
        \d+  # Numbers
    """,
        re.VERBOSE,
    )

    return RE_WORDS.findall(identifier)


def constant_casing(function_name):
    return "_".join([c.upper() for c in camel_case_split(function_name)])


def sol_error_selector(function_name, param_names, param_types):
    selector_name = f"{constant_casing(function_name)}_SELECTOR"
    selector_comment = (
        f'// bytes4(keccak256("{function_name}({",".join(param_types)})"))'
    )
    selector_string = f"bytes4 internal constant {selector_name} = \n    {abi_utils.method_id(function_name, param_types)};"

    return (selector_name, selector_comment, selector_string)


def indent(text):
    lines = text.split("\n")
    return "\n".join([f"    {line}" for line in lines])


def sol_error(function_name, param_names, param_types, selector_name):
    param_types = [
        type + " memory" if type == "bytes" else type for type in param_types
    ]
    if len(param_names) == 0:
        function_header = f"function {function_name}()"
    else:
        params = [" ".join(param) for param in zip(param_types, param_names)]
        params_string = indent(",\n".join(params))
        function_header = f"function {function_name}(\n{params_string}\n)"

    modifiers = indent("internal\npure\nreturns (bytes memory)")

    if len(param_names) == 0:
        return_value = f"return abi.encodeWithSelector({selector_name});"
    else:
        encode_params = indent(",\n".join([selector_name] + param_names))
        return_value = f"return abi.encodeWithSelector(\n{encode_params}\n);"
    function_body = f"{{\n{indent(return_value)}\n}}"

    return f"{function_header}\n{modifiers}\n{function_body}"


def ts_type(sol_type):
    if "int" in sol_type:
        return "BigNumber | number | string"
    else:
        return "string"


# We can be sloppy with the formatting here because prettier will fix it up for us
def ts_error(function_name, param_names, param_types):
    sol_params = [" ".join(param) for param in zip(param_types, param_names)]
    sol_params_string = ", ".join(sol_params)

    ts_params = [
        f"{name}?: {ts_type(sol_type)}"
        for (name, sol_type) in zip(param_names, param_types)
    ]
    ts_params_string = ",".join(ts_params)

    name_string = f"'{function_name}'"
    declaration_string = f"'{function_name}({sol_params_string})'"
    values_string = f'{{ {",".join(param_names)} }}'

    super_string = (
        f'super({",".join([name_string, declaration_string, values_string])});'
    )
    constructor_string = f"constructor({ts_params_string}) {{ {super_string} }}"
    class_string = (
        f"export class {function_name} extends RevertError {{ {constructor_string} }}"
    )

    return class_string


def sol_codegen(lib_name, functions, target):
    error_selectors = []
    error_functions = []

    for function_name, function_obj in functions.items():
        param_names = []
        param_types = []
        for param, props in function_obj.arguments.items():
            param_names.append(param)
            param_types.append(props.typeName.name)

        selector_name, selector_comment, selector_string = sol_error_selector(
            function_name, param_names, param_types
        )
        error_selectors.append(f"{selector_comment}\n{selector_string}")
        error_functions.append(
            sol_error(function_name, param_names, param_types, selector_name)
        )

    shutil.copyfile("constants/sol_prefix.txt", target)
    with open(target, "a") as f:
        f.write(f"\n\nlibrary {lib_name} ")
        f.write("{\n")
        f.write(indent("\n\n".join(error_selectors + error_functions)))
        f.write("\n}")


def ts_codegen(functions, repo, target):
    error_classes = []

    for function_name, function_obj in functions.items():
        param_names = []
        param_types = []
        for param, props in function_obj.arguments.items():
            param_names.append(param)
            param_types.append(props.typeName.name)

        selector_name, _, _ = sol_error_selector(
            function_name, param_names, param_types
        )
        error_classes.append(ts_error(function_name, param_names, param_types))

    shutil.copyfile("constants/ts_prefix.txt", target)
    with open(target, "a") as f:
        f.write("\n\n")
        f.write("\n\n".join(error_classes))
        f.write(f'\n\nconst types = [{",".join(functions.keys())}];\n')
        with open("constants/ts_suffix.txt", "r") as file_suffix:
            for line in file_suffix:
                f.write(line)

    cwd = os.getcwd()
    os.system(f"cd {repo} && yarn prettier && cd {cwd}")


arg_parser = argparse.ArgumentParser(
    description="Generates Solidity rich reverts library and corresponding Typescript classes from boilerplate."
)
arg_parser.add_argument("--repo", help="Absolute path to monorepo.")
arg_parser.add_argument(
    "--sol",
    help="Path (relative to monorepo) to Solidity file containing library boilerplate.",
)
arg_parser.add_argument(
    "--ts",
    help="Path (relative to monorepo) to Typescript file to place error classes.",
)

args = arg_parser.parse_args()

sol_target = f"{args.repo}/{args.sol}"
ts_target = f"{args.repo}/{args.ts}"

sourceUnit = parser.parse_file(sol_target)
sourceUnitObject = parser.objectify(sourceUnit)
contractName = list(sourceUnitObject.contracts.keys())[0]
contractObject = sourceUnitObject.contracts[contractName]

sol_codegen(contractName, contractObject.functions, sol_target)
ts_codegen(contractObject.functions, args.repo, ts_target)
