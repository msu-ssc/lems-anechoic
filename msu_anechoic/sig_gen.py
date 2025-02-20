import contextlib
from typing import TYPE_CHECKING
import pyvisa
from msu_anechoic.spec_an import GpibDevice

if TYPE_CHECKING:
    import logging

class SigGenHP8672A(GpibDevice):
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


if __name__ == "__main__":
    rm = pyvisa.ResourceManager()
    resource_names = rm.list_resources()
    for resource_name in resource_names:
        if resource_name.startswith("GPIB"):
            break

    print(f"Opening {resource_name=}")
    sig_gen = SigGenHP8672A(
        resource_manager=rm,
        gpib_address=resource_name,
        open_immediately=True,
        log_query_messages=True,
    )
    
    print(f"{sig_gen=!r}")
    print(f"{sig_gen=!s}")

    query = "P084500000Z0K3L0M0N6O1"
    print(f"Querying {query=}")
    response = sig_gen.query("P084500000Z0K3L0M0N6O1")
    print(f"{response=}")
