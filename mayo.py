import logging
from typing import Type

from matplotlib import pyplot as plt
import numpy as np

logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    # level=logging.DEBUG,
    level=logging.INFO,
)
logging.info("MAYO")

import sys

logging.debug(f"{sys.path=}")
logging.debug(f"{sys.executable=}")

import pyvisa

rm = pyvisa.ResourceManager()
print(f"{rm=}")
print(f"{rm.visalib=}")
# print(rm.list_resources())

resources = list(
    rm.list_resources(
        query="GPIB?*INSTR",
    )
)

print(f"{resources=}")

# resources.append("GPIB0::13::INSTR")

# exit(1)


def _query_resource(
    resource: "pyvisa.resources.Resource",
    query: str,
    *,
    delay: float = 0.1,
    type: Type = None,
):
    logging.info(f"Querying {resource} with {query=}")
    try:
        result: str = resource.query(query, delay=delay)
    except Exception as exc:
        logging.info(f"Error querying {resource} with {query=}. {exc=}")
        return None

    if type is not None:
        result = type(result.strip())

    return result


def query_float(
    resource: "pyvisa.resources.Resource",
    query: str,
    delay: float = 0.1,
):
    return _query_resource(
        resource=resource,
        query=query,
        delay=delay,
        type=float,
    )


for index, resource in enumerate(resources):
    print(f"\n******************** {index=} {resource=} ********************")
    try:
        inst = rm.open_resource(resource)
        logging.debug(f"{inst=} {type(inst)=}")
        # result = inst.query("*IDN?", delay=0.1)
        # result = inst.query("CF?", delay=0.1)
        try:
            center_frequency = _query_resource(inst, "CF?", delay=0.1, type=float)
            # print(f"{cf=} {type(cf)=}")
        except Exception as exc:
            # print(f"Not a power meter, apparently. {exc=}")
            continue
        if center_frequency is None:
            print(f"Not a power meter, apparently.")
            continue

        
        start_frequency = query_float(inst, "FA?")
        stop_frequency = query_float(inst, "FB?")
        span = query_float(inst, "SP?")

        logging.info(f"{center_frequency=} {start_frequency=} {stop_frequency=} {span=}")


        trace = inst.query("TRA?")
        data = [float(token) for token in trace.strip().split(",")]
        xs = np.linspace(start_frequency, stop_frequency, len(data)) / 1e6
        ys = np.array(data)
        fig, ax = plt.subplots(1, 1)

        ax.plot(xs, ys)
        ax.set_title(f"I did it!")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Power (dBm)")
        plt.show()

        # trace = inst.query("TRA?")
        # data = [float(token) for token in trace.strip().split(",")]
        # print(f"{trace=}")
        # print(f"{data=}")
        print(f"{len(data)=}")
        # print(f"{resource=} {inst=} {result=}")
    except Exception as exc:
        print(f"{exc=} for {resource=}")
        # import traceback
        # traceback.print_exc()
        # break
        continue

# name = "GPIB0::13::INSTR"
# inst = rm.open_resource(resource)
# result = inst.query("CF?")
