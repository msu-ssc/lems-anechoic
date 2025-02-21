import contextlib
from typing import TYPE_CHECKING

import pyvisa

from msu_anechoic import sig_gen_enums
from msu_anechoic.spec_an import GpibDevice

if TYPE_CHECKING:
    import logging


class SigGenHP8672A(GpibDevice):
    """Hewlett-Packard 8672A signal generator.

    See document `HP 8672A Synthesized Signal Generator Operating and Service Manual` section 3 for more information.

    As of February 2025, it is available at [https://www.keysight.com/us/en/assets/9018-05865/user-manuals/9018-05865.pdf?success=true](https://www.keysight.com/us/en/assets/9018-05865/user-manuals/9018-05865.pdf?success=true)

    A copy is in the `./docs/` folder
    """

    @classmethod
    def find(
        cls,
        *,
        logger: "logging.Logger | None" = None,
        resource_manager: pyvisa.highlevel.ResourceManager,
        open_immediately: bool = True,
        log_query_messages: bool = False,
    ) -> "SigGenHP8672A | None":
        resource_manager = resource_manager or pyvisa.ResourceManager()
        resources = resource_manager.list_resources()
        for resource_name in resources:
            if logger:
                logger.debug(f"Checking {resource_name=}")

            if "GPIB" not in resource_name:
                logger.debug(f"Skipping {resource_name=}, because it is not a GPIB device.")
                continue
            try:
                resource: pyvisa.resources.MessageBasedResource = resource_manager.open_resource(resource_name)

                # NOTE: 8563E doesn't respond to "*IDN?", so we have to use something else.
                # Of the GPIB devices at MSU Space Science Center, this is the only one that responds to "CF?".
                response = resource.query("CF?")
            except Exception as exc:
                if logger:
                    logger.debug(f"Error checking {resource=}. {exc}")
                continue
            if response:
                if logger:
                    logger.info(f"Found HP 8563E spectrum analyzer at {resource=}")
                return SigGenHP8672A(
                    gpib_address=resource.resource_name,
                    logger=logger,
                    resource_manager=resource_manager,
                    open_immediately=open_immediately,
                    log_query_messages=log_query_messages,
                )

        # nullcontext is a context manager that does nothing. It evaluates to `None` in an `as` clause.
        return contextlib.nullcontext()

    @classmethod
    def create_command(
        cls,
        *,
        frequency: float | None = None,
        fm: sig_gen_enums.FM | None = None,
        alc: sig_gen_enums.ALC | None = None,
        am: sig_gen_enums.AM | None = None,
        output_level_range: sig_gen_enums.OutputLevelRange | None = None,
        output_level_vernier: sig_gen_enums.OutputLevelVernier | None = None,
    ) -> str:
        command = ""

        if frequency is not None:
            program_code = sig_gen_enums.ProgramCode.from_frequency(frequency)

            # Frequency needs to be an integer of precisely 8 digits,
            # left-aligned and zero padded (if necessary) on the right, like the mantissa
            # of scientific notation (but without the decimal point).
            #
            # So 12345.6 becomes "12345600" and 123.456789123456 becomes "12345678"
            frequency_int = int(frequency)
            frequency_str = f"{frequency_int:08d}"[:8]

            # Format is PROGRAM_CODE + FREQUENCY (left-aligned+ "Z0"
            command += f"{program_code.value}{frequency_str}Z0"

        if fm is not None:
            command += "N" + fm.value

        if alc is not None:
            command += "O" + alc.value

        if output_level_range is not None:
            command += "K" + output_level_range.value

        if output_level_vernier is not None:
            command += "L" + output_level_vernier.value

        if am is not None:
            command += "M" + am.value

        return command
        pass


if __name__ == "__main__":
    from msu_ssc import ssc_log

    ssc_log.init(level="DEBUG")

    logger = ssc_log.logger.getChild("sig_gen")

    command = SigGenHP8672A.create_command(
        frequency=8_450_000_000,
        fm=sig_gen_enums.FM.OFF,
        alc=sig_gen_enums.ALC.INT_NORMAL,
        am=sig_gen_enums.AM.OFF,
        output_level_range=sig_gen_enums.OutputLevelRange.NEGATIVE_30_DBM,
        output_level_vernier=sig_gen_enums.OutputLevelVernier.PLUS_THREE_DB,
    )
    print(f"{command=}")
    # exit()

    # rm = pyvisa.ResourceManager()
    # resource_names = rm.list_resources()
    # for resource_name in resource_names:
    #     if resource_name.startswith("GPIB"):
    #         break

    resource_name = "GPIB0::MAYO_FILL_THIS_IN::INSTR"

    print(f"Opening {resource_name=}")
    with SigGenHP8672A(
        # resource_manager=rm,
        gpib_address=resource_name,
        open_immediately=True,
        log_query_messages=True,
        logger=logger,
    ) as sig_gen:
        print(f"{sig_gen=!r}")
        print(f"{sig_gen=!s}")

        logger.info(f"Attempting to read one byte")
        data = sig_gen.resource.read_raw(1)
        logger.info(f"Read one byte: {data=}")

        # command = "P084500000Z0K3L0M0N6O1"
        command = sig_gen.create_command(
            frequency=8_450_000_000,
        )
        logger.info(f"Writing {command=}")
        sig_gen.resource.write(command)

        logger.info(f"Reading response")
        data = sig_gen.resource.read_raw(1)
        logger.info(f"Read one byte: {data=}")

        # sig_gen.resource.read_raw
        # print(f"{sig_gen.read}")
        # print(f"Querying {command=}")
        # response = sig_gen.query("P084500000Z0K3L0M0N6O1")
        # print(f"{response=}")
