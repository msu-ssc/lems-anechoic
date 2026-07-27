#!/usr/bin/env python3
"""Query the HP 8563E center frequency through Keysight VISA on Linux."""

from __future__ import annotations

import argparse
import math

import pyvisa
from pyvisa.resources import GPIBInstrument
from pyvisa.resources import MessageBasedResource

DEFAULT_VISA_LIBRARY = "/opt/keysight/iolibs/libvisa.so"
DEFAULT_RESOURCE = "GPIB0::18::INSTR"
DEFAULT_EXPECTED_HZ = 390_000_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send the read-only query CF? to an HP 8563E over GPIB.",
    )
    parser.add_argument(
        "--visa-library",
        default=DEFAULT_VISA_LIBRARY,
        help=f"VISA shared library (default: {DEFAULT_VISA_LIBRARY})",
    )
    parser.add_argument(
        "--resource",
        default=DEFAULT_RESOURCE,
        help=f"VISA resource name (default: {DEFAULT_RESOURCE})",
    )
    parser.add_argument(
        "--expected-hz",
        type=float,
        default=DEFAULT_EXPECTED_HZ,
        help=f"Expected center frequency (default: {DEFAULT_EXPECTED_HZ:g})",
    )
    parser.add_argument(
        "--relative-tolerance",
        type=float,
        default=0.01,
        help="Allowed relative difference from --expected-hz (default: 0.01)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5_000,
        help="VISA I/O timeout in milliseconds (default: 5000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"Loading VISA library: {args.visa_library}")
    resource_manager = pyvisa.ResourceManager(args.visa_library)
    resources = resource_manager.list_resources()
    for resource in resources:
        print(f"{resource=}")
    print(f"Opening resource: {args.resource}")
    instrument: MessageBasedResource = resource_manager.open_resource(
        args.resource,
        open_timeout=args.timeout_ms,
    )

    print(f"{instrument=}")
    print(f"{type(instrument)=}")

    try:
        instrument.timeout = args.timeout_ms
        print("Sending query: CF?")
        raw_response = instrument.query("CF?")
        print(f"Raw response: {raw_response!r}")

        center_frequency_hz = float(raw_response.strip())
        print(f"Parsed center frequency: {center_frequency_hz:g} Hz")

        if not math.isfinite(center_frequency_hz):
            print("FAIL: response is not a finite number")
            return 1

        if not math.isclose(
            center_frequency_hz,
            args.expected_hz,
            rel_tol=args.relative_tolerance,
        ):
            print(f"FAIL: response is outside the expected range around {args.expected_hz:g} Hz")
            return 2

        print("PASS: GPIB query returned the expected center frequency")
        return 0
    finally:
        instrument.close()
        resource_manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
