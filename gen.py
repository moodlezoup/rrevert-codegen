import argparse
import os
import re
import shutil

from solidity_parser import parser
from zero_ex.dev_utils import abi_utils


ORDER_UTILS_DIR = "packages/order-utils/src"


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


def upper_camel_casing(enum_value):
    return "".join([c.lower().capitalize() for c in enum_value.split("_")])


def constant_casing(function_name):
    return "_".join([c.upper() for c in camel_case_split(function_name)])


def indent(text):
    lines = text.split("\n")
    return "\n".join([f"    {line}" for line in lines])


def params(function_obj, convertEnums=False, bytesMemory=False):
    param_names = []
    param_types = []

    for param, props in function_obj.arguments.items():
        param_names.append(param)
        if "name" in props.typeName:
            type = props.typeName.name
            param_types.append(
                type + " memory" if bytesMemory and type == "bytes" else type
            )
        else:
            param_types.append("uint8" if convertEnums else props.typeName.namePath)

    return param_names, param_types


def ts_type(sol_type, enums):
    if sol_type in enums:
        return sol_type
    elif "int" in sol_type:
        return "BigNumber | number | string"
    else:
        return "string"


def get_ts_target(repo, lib_path):
    m = re.match(r"Lib(\w+)RichErrors.sol", lib_path.split("/")[-1])
    identifier = m.group(1).lower()
    return f"{repo}/{ORDER_UTILS_DIR}/{identifier}_revert_errors.ts"


def sol_error_selector(function_name, function_obj):
    param_names, param_types = params(function_obj, convertEnums=True)

    if len(param_names) == 0:
        selector_name = f"{constant_casing(function_name)}"
        selector_string = f'bytes internal constant {selector_name} =\n    hex"{abi_utils.method_id(function_name, param_types)[2:]}";'
    else:
        selector_name = f"{constant_casing(function_name)}_SELECTOR"
        selector_string = f"bytes4 internal constant {selector_name} =\n    {abi_utils.method_id(function_name, param_types)};"

    selector_comment = (
        f'// bytes4(keccak256("{function_name}({",".join(param_types)})"))'
    )

    return (selector_name, selector_comment, selector_string)


def sol_error(function_name, function_obj, selector_name):
    param_names, param_types = params(
        function_obj, convertEnums=False, bytesMemory=True
    )

    if len(param_names) == 0:
        function_header = f"function {function_name}()"
    else:
        params_string = indent(
            ",\n".join([" ".join(param) for param in zip(param_types, param_names)])
        )
        function_header = f"function {function_name}(\n{params_string}\n)"

    modifiers = indent("internal\npure\nreturns (bytes memory)")

    if len(param_names) == 0:
        return_value = f"return {selector_name};"
    else:
        encode_params = indent(",\n".join([selector_name] + param_names))
        return_value = f"return abi.encodeWithSelector(\n{encode_params}\n);"
    function_body = f"{{\n{indent(return_value)}\n}}"

    return f"{function_header}\n{modifiers}\n{function_body}"


# We can be sloppy with the formatting here because prettier will fix it up for us
def ts_error(function_name, function_obj, enums):
    declaration_param_names, declaration_param_types = params(
        function_obj, convertEnums=True
    )
    declaration_params = [
        " ".join(param)
        for param in zip(declaration_param_types, declaration_param_names)
    ]
    declaration_params_string = ", ".join(declaration_params)

    param_names, param_types = params(function_obj)
    ts_params = [
        f"{name}?: {ts_type(sol_type, enums)}"
        for (name, sol_type) in zip(param_names, param_types)
    ]
    ts_params_string = ",".join(ts_params)

    name_string = f"'{function_name}'"
    declaration_string = f"'{function_name}({declaration_params_string})'"
    values_string = f'{{ {",".join(param_names)} }}'

    super_string = (
        f'super({",".join([name_string, declaration_string, values_string])});'
    )
    constructor_string = f"constructor({ts_params_string}) {{ {super_string} }}"
    class_string = (
        f"export class {function_name} extends RevertError {{ {constructor_string} }}"
    )

    return class_string


def sol_codegen(lib_name, contract, target):
    error_code_enums = []
    for enum_name, enum_obj in contract.enums.items():
        error_codes = indent(",\n".join([c.name for c in enum_obj.members]))
        enum_str = f"enum {enum_name} {{\n{error_codes}\n}}"
        error_code_enums.append(enum_str)

    error_selectors = []
    error_functions = []

    for function_name, function_obj in contract.functions.items():
        selector_name, selector_comment, selector_string = sol_error_selector(
            function_name, function_obj
        )
        error_selectors.append(f"{selector_comment}\n{selector_string}")
        error_functions.append(sol_error(function_name, function_obj, selector_name))

    shutil.copyfile("constants/sol_prefix.txt", target)
    with open(target, "a") as f:
        f.write(f"\n\nlibrary {lib_name} ")
        f.write("{\n")
        f.write("\n\n".join([indent(e) for e in error_code_enums]))
        f.write("\n\n")
        f.write("\n\n".join([indent(s) for s in error_selectors]))
        f.write(f'\n\n{indent("// solhint-disable func-name-mixedcase")}\n')
        f.write("\n\n".join([indent(f) for f in error_functions]))
        f.write("\n}\n")


def ts_codegen(contract, repo, target):
    error_code_enums = []
    for enum_name, enum_obj in contract.enums.items():
        error_codes = ",".join([upper_camel_casing(c.name) for c in enum_obj.members])
        enum_str = f"export enum {enum_name} {{ {error_codes} }}"
        error_code_enums.append(enum_str)

    error_classes = []
    for function_name, function_obj in contract.functions.items():
        error_classes.append(ts_error(function_name, function_obj, contract.enums))

    shutil.copyfile("constants/ts_prefix.txt", target)
    with open(target, "a") as f:
        f.write("\n\n")
        f.write("\n\n".join(error_code_enums))
        f.write("\n\n")
        f.write("\n\n".join(error_classes))
        f.write(f'\n\nconst types = [{",".join(contract.functions.keys())}];\n')
        with open("constants/ts_suffix.txt", "r") as file_suffix:
            for line in file_suffix:
                f.write(line)

    cwd = os.getcwd()
    os.system(
        f"cd {repo} && node ./node_modules/.bin/prettier --write {target} --config .prettierrc && cd {cwd}"
    )


arg_parser = argparse.ArgumentParser(
    description="Generates Solidity rich reverts library and corresponding Typescript classes from boilerplate."
)
arg_parser.add_argument("--repo", help="Absolute path to monorepo.")
arg_parser.add_argument(
    "--lib_path",
    help="Path (relative to monorepo) to Solidity file containing library boilerplate.",
)

args = arg_parser.parse_args()

sol_target = f"{args.repo}/{args.lib_path}"
ts_target = get_ts_target(args.repo, args.lib_path)

sourceUnit = parser.parse_file(sol_target)
sourceUnitObject = parser.objectify(sourceUnit)
contractName = list(sourceUnitObject.contracts.keys())[0]
contractObject = sourceUnitObject.contracts[contractName]

sol_codegen(contractName, contractObject, sol_target)
ts_codegen(contractObject, args.repo, ts_target)
