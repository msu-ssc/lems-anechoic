/*
 * Minimal Keysight/IVI VISA proof of concept for the HP 8563E.
 *
 * This program is intentionally independent of the lems-anechoic Python
 * package. It performs one read-only instrument query:
 *
 *     CF?
 *
 * Build:
 *
 *     g++ -Wall -Wextra -Wpedantic -O2 \
 *       -I/opt/keysight/iolibs/include \
 *       linux_gpib/visa_cf_query.cpp \
 *       -L/opt/keysight/iolibs \
 *       -Wl,-rpath,/opt/keysight/iolibs \
 *       -lvisa \
 *       -o linux_gpib/visa_cf_query
 *
 * Run:
 *
 *     ./linux_gpib/visa_cf_query
 *
 * An alternate VISA resource name may be supplied as the first argument.
 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <visa.h>

enum {
    RESPONSE_CAPACITY = 256,
    TIMEOUT_MS = 5000,
};

static void print_visa_error(ViSession session, const char *operation, ViStatus status)
{
    ViChar description[256] = {0};

    fprintf(stderr, "%s failed with VISA status %ld", operation, (long)status);
    if (session != VI_NULL && viStatusDesc(session, status, description) >= VI_SUCCESS) {
        fprintf(stderr, " (%s)", description);
    }
    fputc('\n', stderr);
}

int main(int argc, char **argv)
{
    const ViRsrc resource_name =
        (ViRsrc)(argc >= 2 ? argv[1] : "GPIB0::18::INSTR");
    const ViByte command[] = "CF?";
    ViSession resource_manager = VI_NULL;
    ViSession instrument = VI_NULL;
    ViStatus status;
    ViUInt32 bytes_written = 0;
    ViUInt32 bytes_read = 0;
    ViByte response[RESPONSE_CAPACITY] = {0};
    char *parse_end = NULL;
    double center_frequency_hz;

    printf("Opening VISA resource manager\n");
    status = viOpenDefaultRM(&resource_manager);
    if (status < VI_SUCCESS) {
        print_visa_error(VI_NULL, "viOpenDefaultRM", status);
        return 1;
    }

    printf("Opening %s with a %d ms timeout\n", resource_name, TIMEOUT_MS);
    status = viOpen(
        resource_manager,
        resource_name,
        VI_NULL,
        TIMEOUT_MS,
        &instrument
    );
    if (status < VI_SUCCESS) {
        print_visa_error(resource_manager, "viOpen", status);
        viClose(resource_manager);
        return 2;
    }

    status = viSetAttribute(instrument, VI_ATTR_TMO_VALUE, TIMEOUT_MS);
    if (status < VI_SUCCESS) {
        print_visa_error(instrument, "viSetAttribute(VI_ATTR_TMO_VALUE)", status);
        viClose(instrument);
        viClose(resource_manager);
        return 3;
    }

    printf("Writing query: %s\n", command);
    status = viWrite(
        instrument,
        (ViBuf)command,
        (ViUInt32)strlen((const char *)command),
        &bytes_written
    );
    if (status < VI_SUCCESS) {
        print_visa_error(instrument, "viWrite", status);
        viClose(instrument);
        viClose(resource_manager);
        return 4;
    }
    printf("Wrote %u bytes\n", bytes_written);

    status = viRead(
        instrument,
        response,
        RESPONSE_CAPACITY - 1,
        &bytes_read
    );
    if (status < VI_SUCCESS) {
        print_visa_error(instrument, "viRead", status);
        viClose(instrument);
        viClose(resource_manager);
        return 5;
    }

    response[bytes_read] = '\0';
    printf("Raw response (%u bytes): %s\n", bytes_read, response);

    errno = 0;
    center_frequency_hz = strtod((const char *)response, &parse_end);
    if (errno != 0 || parse_end == (char *)response) {
        fprintf(stderr, "The response is not numeric.\n");
        viClose(instrument);
        viClose(resource_manager);
        return 6;
    }

    printf("Parsed center frequency: %.12g Hz\n", center_frequency_hz);

    viClose(instrument);
    viClose(resource_manager);
    return 0;
}
