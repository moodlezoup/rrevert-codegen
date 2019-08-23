# rrevert-codegen
Generates .sol/.ts files for rich reverts from boilerplate

Requirements: [This fork](https://github.com/mzhu25/python-solidity-parser) for `solidity_parser` and `pip install 0x-order-utils`

`python gen.py --repo {/absolute/path/to/monorepo}` --lib_path {relative/path/from/monorepo/to/richerror/lib}`

[Example](https://github.com/0xProject/0x-monorepo/commit/cb36c3cde3f0bbdef6d8c9792ea29519d270970c)
