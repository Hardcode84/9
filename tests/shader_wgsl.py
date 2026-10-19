# SPDX-License-Identifier: Apache-2.0
"""Translate WGSL with the pinned Naga CLI."""


def translate_wgsl(run, validator, source, output, environment):
    return run([validator.resolve(), source, output], env=environment)
