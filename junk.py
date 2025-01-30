def get_sample_output():
    return b"...\r\nEl: -12.345, Az: -67.890\r\n..."


#region ORIGINAL_CODE
print(f"\n\n*************** ORIGINAL CODE ***************")
a = get_sample_output()
b = str(a, "ascii")
point1 = b.index("El:")
point2 = b.index("\r", point1)
parts = [i.strip() for i in b[point1:point2].split(",")]
el_az_list = [float(i.split(" ")[1]) for i in parts]
print(el_az_list)
#endregion ORIGINAL_CODE

#region BETTER_VARIABLES
print(f"\n\n*************** SAME CODE, BETTER VARIABLE NAMES ***************")
control_box_output_raw = get_sample_output()
control_box_output_string = str(control_box_output_raw, "ascii")
el_az_start_index = control_box_output_string.index("El:")
el_az_data_end_index = control_box_output_string.index("\r", el_az_start_index)
parts = [i.strip() for i in control_box_output_string[el_az_start_index:el_az_data_end_index].split(",")]
el_az_list = [float(i.split(" ")[1]) for i in parts]
print(el_az_list)
#endregion BETTER_VARIABLES

#region MORE_EXPLICIT
print(f"\n\n*************** SAME CODE, MORE EXPLICIT CODE + COMMENTS ***************")
control_box_output_raw = get_sample_output()
control_box_output_string = str(control_box_output_raw, "ascii")    # Python str, like "...\r\nEl: -12.345, Az: -67.890\r\n..."
el_az_start_index = control_box_output_string.index("El:")          # location of "El:" in the string
el_az_data_end_index = control_box_output_string.index("\r", el_az_start_index)     # location of the next "\r" after "El:"
el_az_string = control_box_output_string[el_az_start_index:el_az_data_end_index]    # the string containing the elevation and azimuth values
                                                                                    # like "El: -12.345, Az: -67.890"
parts = [i.strip() for i in el_az_string.split(",")]    # A list like ["El: -12.345", "Az: -67.890"]
el_az_list = [float(i.split(" ")[1]) for i in parts]    # A list like [-12.345, -67.890]
print(el_az_list)
#endregion MORE_EXPLICIT

#region FUNCTION
print(f"\n\n*************** SAME CODE, IN A FUNCTION ***************")
def extract_elevation_azimuth(control_box_output_raw: bytes) -> list[float]:
    """
    Extract elevation and azimuth values from the raw output of a control box.

    The control box output is expected to be in the following format:
    `b"...\\r\\nEl: -12.345, Az: -67.890\\r\\n..."`

    Args:
        control_box_output_raw (bytes): The raw byte output from the control box.

    Returns:
        list[float]: A list containing the elevation and azimuth values as floats.
    """
    control_box_output_string = str(control_box_output_raw, "ascii")    # Python str, like "...\r\nEl: -12.345, Az: -67.890\r\n..."
    el_az_start_index = control_box_output_string.index("El:")          # location of "El:" in the string
    el_az_data_end_index = control_box_output_string.index("\r", el_az_start_index)     # location of the next "\r" after "El:"
    el_az_string = control_box_output_string[el_az_start_index:el_az_data_end_index]    # the string containing the elevation and azimuth values
                                                                                        # like "El: -12.345, Az: -67.890"
    parts = [i.strip() for i in el_az_string.split(",")]    # A list like ["El: -12.345", "Az: -67.890"]
    el_az_list = [float(i.split(" ")[1]) for i in parts]    # A list like [-12.345, -67.890]
    return el_az_list

control_box_output_raw = get_sample_output()
el_az_list = extract_elevation_azimuth(control_box_output_raw)
print(el_az_list)
#endregion FUNCTION

