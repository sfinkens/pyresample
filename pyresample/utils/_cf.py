#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Pyresample developers
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.


def _load_crs_from_cf(nc_handle, grid_mapping_varname):
    """ use pyproj to parse the content of the grid_mapping variable and initialize a crs object """
    from pyproj import CRS
    # here we assume the grid_mapping_varname exists (checked by caller)
    return CRS.from_cf(vars(nc_handle[grid_mapping_varname]))


def _is_valid_coordinate_variable(nc_handle, coord_varname, axis):
    """ check if a coord_varname is a valid CF coordinate variable """
    if axis not in ('x', 'y'):
        raise ValueError("axis= parameter must be 'x' or 'y'")
    coord_var = nc_handle[coord_varname]
    valid = False
    try:
        valid = getattr(coord_var, 'standard_name') == 'projection_'+axis+'_coordinate'
    except AttributeError:
        valid = False
    return valid


def _load_axis_info(nc_handle, coord_varname):
    """ load extent and length for the axis held in coord_varname (min, max, len) """

    # this requires reading the data
    values = nc_handle[coord_varname][:]
    try:
        unit = nc_handle[coord_varname].units
    except AttributeError:
        unit = 'default'

    # spacing
    #   TBC: a) should we check the axis has constant spacing or does CF impose this already ?
    #         b) is a single diff enough, or should we take a mean of several (rounding error) ?
    spacing = abs(values[1] - values[0])

    # extent (0,5*spacing is because area_def expects corner coordinates of the corner cells,
    #     while CF stores center coords)
    extent_low = values.min() - 0.5 * spacing
    extent_hgh = values.max() + 0.5 * spacing

    #print (coord_varname , values[0], spacing , extent_low, extent_hgh, unit)

    # now we take into account the units
    scalef = 1.
    if unit != 'default':
        if unit == 'km':
            scalef = 1000.
        elif unit == 'm' or unit == 'meters':
            scalef = 1.
        else:
            raise ValueError("Sorry: un-supported unit: {}!".format(unit))

    extent_low *= scalef
    extent_hgh *= scalef

    return extent_low, extent_hgh, len(values)


def load_cf_area(nc_file, variable=None, y=None, x=None, ):
    """ Load an area def object from a netCDF/CF file. """

    from netCDF4 import Dataset
    from pyresample import geometry
    from pyresample.utils import proj4_str_to_dict

    # basic check on the default values of the parameters.
    if (x is not None and y is None) or (x is None and y is not None):
        raise ValueError("You must specify either all or none of x= and y=")

    # the nc_file can be either the path to a netCDF/CF file, or directly an opened netCDF4.Dataset()
    #   if the path to a file, open the Dataset access to it
    if not isinstance(nc_file, Dataset):
        try:
            nc_file = Dataset(nc_file)
        except FileNotFoundError:
            raise FileNotFoundError('File not found: {}'.format(nc_file))
        except OSError:
            raise ValueError('File is not a netCDF file {}'.format(nc_file))

    # if the variable=None, we search for a good variable
    if variable is None:
        variable = 'good variable'
        raise NotImplementedError("search for a good variable is not implemented yet!")
    else:
        # the variable= must exist in the netCDF file
        if variable not in nc_file.variables.keys():
            raise ValueError("Variable '{}' does not exist in netCDF file".format(variable))

    # Load a CRS object
    # =================
    variable_is_itself_gridmapping = False
    # test if the variable has a grid_mapping attribute
    if hasattr(nc_file[variable], 'grid_mapping'):
        # good. attempt to load the grid_mapping information into a pyproj object
        crs = _load_crs_from_cf(nc_file, nc_file[variable].grid_mapping)
    else:
        # the variable doesn't have a grid_mapping attribute.
        # ... maybe it is the grid_mapping variable itself?
        try:
            variable_is_itself_gridmapping = True
            crs = _load_crs_from_cf(nc_file, variable)
        except Exception as ex:
            # ... not a valid grid_mapping either
            crs = 'a crs'
            raise NotImplementedError(
                "At present, the variable= provided must have a 'grid_mapping' attribute, or must be the name of a valid grid_mapping variable")

    # compute the AREA_EXTENT
    # =======================

    # test if we can allow None for y and x
    if variable_is_itself_gridmapping and (y is None or x is None):
        raise ValueError("When variable= points to the grid_mapping variable itself, y= and x= must be provided")

    # if y= or x= are None, guess the variable names
    xy = dict()
    if y is None and x is None:
        # the name of y and x are in the dimensions of the variable=
        for dim in nc_file[variable].dimensions:
            # test if each dim is a valid CF coordinate variable
            for axis in ('x', 'y'):
                if _is_valid_coordinate_variable(nc_file, dim, axis):
                    xy[axis] = dim

        # did we manage to guess both y= and x= ?
        for axis in ('x', 'y'):
            if axis not in xy.keys():
                raise ValueError("Cannot guess coordinate variable holding the '{}' axis".format(axis))

    else:
        # y= and x= are provided by the caller. Check they are valid CF coordinate variables
        #   The order is always (y,x)
        xy['y'] = y
        xy['x'] = x
        for axis in ('x', 'y'):
            if not _is_valid_coordinate_variable(nc_file, xy[axis], axis):
                raise ValueError(
                    "Variable x='{}' is not a valid CF coordinate variable for the {} axis".format(xy[axis], axis))

    # we now have the names for the x= and y= coordinate variables: load the extent of each axis separately
    axis_info = dict()
    for axis in xy.keys():
        axis_info[axis] = _load_axis_info(nc_file, xy[axis])

    # create the shape, and area_extent arrays
    shape = (axis_info['y'][2], axis_info['x'][2])
    extent = (axis_info['x'][0], axis_info['y'][0], axis_info['x'][1], axis_info['y'][1])

    # transform the crs objecto a proj_dict (might not be needed in future versions of pyresample)
    proj_dict = crs.to_dict()

    # now we have all we need to create an area definition
    return geometry.AreaDefinition.from_extent('from_cf', proj_dict, shape, extent,)
