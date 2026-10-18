# Security Policy

## Supported versions

`prodc` is pre-1.0. Only the latest release on PyPI is supported. Fixes land on `main`
and ship in the next automatic release; there are no backports.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Email **jorgeecardona@gmail.com** with a description, the affected version, and steps to
reproduce. You can expect an acknowledgement within a few days. Once a fix is released, the
report will be credited unless you ask otherwise.

## Scope

`prodc` reads YAML specs (`prodc.toml`, `product/needs/*.yaml`) and locates tests in your
repository. It runs none of your project code, but it does parse YAML and write back to the
files you point it at. Treat specs from an untrusted source as you would any other input.
