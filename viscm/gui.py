# This file is part of viscm
# Copyright (C) 2015 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2015 Stefan van der Walt <stefanv@berkeley.edu>
# Copyright (C) 2020 Ellert van der Velden <ellert_vandervelden@outlook.com>
# See file LICENSE.txt for license information.

# Simple script using CIECAM02 and CAM02-UCS to visualize properties of a
# matplotlib colormap
import sys
import os.path
import json

import numpy as np

from qtpy import QtCore as QC, QtWidgets as QW
from guipy import layouts as GL, widgets as GW
from guipy.widgets import get_box_value, get_modified_signal, set_box_value
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas)

import matplotlib
import matplotlib.pyplot as plt
import mpl_toolkits.mplot3d
from matplotlib.gridspec import GridSpec
import matplotlib.colors
from matplotlib.colors import ListedColormap, TwoSlopeNorm

from colorspacious import (cspace_converter, cspace_convert,
                           CIECAM02Space, CIECAM02Surround)
from .minimvc import Trigger
from .bezierbuilder import (
        SingleBezierCurveModel, TwoBezierCurveModel, ControlPointBuilder,
        ControlPointModel)

from cmasher import get_cmap_type


# The correct L_A value for the standard sRGB viewing conditions is:
#   (64 / np.pi) / 5
# Due to an error in our color conversion code, the matplotlib colormaps were
# designed using the assumption that they would be viewed with an L_A value of
#   (64 / np.pi) * 5
# (i.e., 125x brighter ambient illumination than appropriate). It turns out
# that when all is said and done this has negligible effect on the uniformity
# of the resulting colormaps (phew), BUT fixing the bug has the effect of
# somewhat shrinking the sRGB color solid as projected into CAM02-UCS
# space. This means that the bezier points for existing colormaps (like the
# matplotlib ones) are in the wrong place. We can reproduce the original
# colormaps from these points by using this buggy_CAM02UCS space as our
# uniform space:
buggy_sRGB_viewing_conditions = CIECAM02Space(
    XYZ100_w="D65",
    Y_b=20,
    L_A=(64 / np.pi) * 5,  # bug: should be / 5
    surround=CIECAM02Surround.AVERAGE)
buggy_CAM02UCS = {"name": "CAM02-UCS",
                  "ciecam02_space": buggy_sRGB_viewing_conditions,
                  }

GREYSCALE_CONVERSION_SPACE = "JCh"

_sRGB1_to_JCh = cspace_converter("sRGB1", GREYSCALE_CONVERSION_SPACE)
_JCh_to_sRGB1 = cspace_converter(GREYSCALE_CONVERSION_SPACE, "sRGB1")


def to_greyscale(sRGB1):
    JCh = _sRGB1_to_JCh(sRGB1)
    JCh[..., 1] = 0
    return np.clip(_JCh_to_sRGB1(JCh), 0, 1)


_deuter50_space = {"name": "sRGB1+CVD",
                   "cvd_type": "deuteranomaly",
                   "severity": 50}
_deuter50_to_sRGB1 = cspace_converter(_deuter50_space, "sRGB1")
_deuter100_space = {"name": "sRGB1+CVD",
                    "cvd_type": "deuteranomaly",
                    "severity": 100}
_deuter100_to_sRGB1 = cspace_converter(_deuter100_space, "sRGB1")
_prot50_space = {"name": "sRGB1+CVD",
                 "cvd_type": "protanomaly",
                 "severity": 50}
_prot50_to_sRGB1 = cspace_converter(_prot50_space, "sRGB1")
_prot100_space = {"name": "sRGB1+CVD",
                  "cvd_type": "protanomaly",
                  "severity": 100}
_prot100_to_sRGB1 = cspace_converter(_prot100_space, "sRGB1")


def _show_cmap(ax, rgb):
    ax.imshow(rgb[np.newaxis, ...], aspect="auto")


def _apply_rgb_mat(mat, rgb):
    return np.clip(np.einsum("...ij,...j->...i", mat, rgb), 0, 1)


# sRGB corners: a' goes from -37.4 to 45
AP_LIM = (-38, 46)
# b' goes from -46.5 to 42
BP_LIM = (-47, 43)
# J'/K goes from 0 to 100
JP_LIM = (-1, 101)


def _setup_Jpapbp_axis(ax):
    ax.set_xlabel("a' (green -> red)")
    ax.set_ylabel("b' (blue -> yellow)")
    ax.set_zlabel("J'/K (black -> white)")
    ax.set_xlim(*AP_LIM)
    ax.set_ylim(*BP_LIM)
    ax.set_zlim(*JP_LIM)


# Adapt a matplotlib colormap to a linearly transformed version -- useful for
# visualizing how colormaps look given color deficiency.
# Kinda a hack, b/c we inherit from Colormap (this is required), but then
# ignore its implementation entirely.
class TransformedCMap(matplotlib.colors.Colormap):
    def __init__(self, transform, base_cmap):
        self.transform = transform
        self.base_cmap = base_cmap

    def __call__(self, *args, **kwargs):
        bts = kwargs.pop('bytes', False)
        fx = self.base_cmap(*args, bytes=False, **kwargs)
        tfx = self.transform(fx)
        if bts:
            return (tfx * 255).astype('uint8')
        return tfx

    def set_bad(self, *args, **kwargs):
        self.base_cmap.set_bad(*args, **kwargs)

    def set_under(self, *args, **kwargs):
        self.base_cmap.set_under(*args, **kwargs)

    def set_over(self, *args, **kwargs):
        self.base_cmap.set_over(*args, **kwargs)

    def is_gray(self):
        return False


def _vis_axes(fig):
    grid = GridSpec(10, 4,
                    left=0.02,
                    right=0.98,
                    bottom=0.02,
                    width_ratios=[1] * 4,
                    height_ratios=[1] * 10)
    axes = {'cmap': grid[0, 0],
            'deltas': grid[1:4, 0],

            'cmap-greyscale': grid[0, 1],
            'lightness-deltas': grid[1:4, 1],

            'deuteranomaly': grid[4, 0],
            'deuteranopia': grid[5, 0],
            'protanomaly': grid[4, 1],
            'protanopia': grid[5, 1],

            # 'lightness': grid[4:6, 1],
            # 'colourfulness': grid[4:6, 2],
            # 'hue': grid[4:6, 3],

            'image0': grid[0:3, 2],
            'image0-cb': grid[0:3, 3],
            'image1': grid[3:6, 2],
            'image1-cb': grid[3:6, 3],
            'image2': grid[6:8, 2:],
            'image2-cb': grid[8:, 2:]
            }

    axes = dict([(key, fig.add_subplot(value))
                 for (key, value) in axes.items()])
    axes['gamut'] = fig.add_subplot(grid[6:, :2], projection='3d')
    return axes


def lookup_colormap_by_name(name):
    try:
        return plt.get_cmap(name)
    except ValueError:
        pass
    # Try expanding a setuptools-style entrypoint:
    #   foo.bar:baz.quux
    #   -> import foo.bar; return foo.bar.baz.quux
    if ":" in name:
        module_name, object_name = name.split(":", 1)
        object_path = object_name.split(".")
        import importlib
        cm = importlib.import_module(module_name)
        for entry in object_path:
            cm = getattr(cm, entry)
        return cm
    raise ValueError("Can't find colormap {!r}".format(name))


class viscm(object):
    def __init__(self, cm, figure=None, uniform_space="CAM02-UCS",
                 name=None, N_dots=50, show_gamut=False):
        if isinstance(cm, str):
            cm = lookup_colormap_by_name(cm)
        if name is None:
            name = cm.name
        if figure is None:
            figure = plt.figure()
        self._sRGB1_to_uniform = cspace_converter("sRGB1", uniform_space)

        self.figure = figure
        self.figure.suptitle("Colormap evaluation: %s" % (name,), fontsize=24)

        axes = _vis_axes(self.figure)
        cmtype = get_cmap_type(cm)

        # ListedColormap is used for many matplotlib builtin colormaps
        # (e.g. viridis) and also what we use in the editor. It's the most
        # efficient way to work with arbitrary smooth colormaps -- pick enough
        # points that it looks smooth, and then don't waste time interpolating
        # between them. But then it creates weird issues in the analyzer if
        # our N doesn't match their N, especially when we try to compute the
        # derivative. (Specifically the derivative oscillates between 0 and a
        # large value depending on where our sample points happen to fall
        # relative to the cutoffs between the ListedColormap samples.) So if
        # this is a smooth (large N) ListedColormap, then just use its samples
        # directly:
        N = cm.N
        if isinstance(cm, ListedColormap) and cm.N >= 100:
            RGB = np.asarray(cm.colors)[:, :3]
            N = RGB.shape[0]
            x = np.linspace(0, 1, N)
        else:
            x = np.linspace(0, 1, N)
            RGB = cm(x)[:, :3]
        x_dots = np.linspace(0, 1, N_dots, (cmtype != 'cyclic'))
        RGB_dots = cm(x_dots)[:, :3]

        ax = axes['cmap']
        _show_cmap(ax, RGB)
        ax.set_title("The colormap in its glory")
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)

        def label(ax, s):
            ax.text(0.95, 0.05, s,
                    horizontalalignment="right",
                    verticalalignment="bottom",
                    transform=ax.transAxes)

        def title(ax, s):
            ax.text(0.98, 0.98, s,
                    horizontalalignment="right",
                    verticalalignment="top",
                    transform=ax.transAxes)

        Jpapbp = self._sRGB1_to_uniform(RGB)

        def delta_ymax(values):
            return max(np.max(values)*1.1, 0)

        ax = axes['deltas']
        local_deltas = np.sqrt(np.sum(np.diff(Jpapbp, axis=0)**2, axis=-1))
        local_derivs = (N-1)*local_deltas
        ax.plot(x[1:], local_derivs)
        arclength = np.sum(local_deltas)
        rmse = np.std(local_derivs)
        title(ax, "Perceptual derivative")
        label(ax, "Length: %0.1f\nRMS deviation from flat: %0.1f (%0.1f%%)"
              % (arclength, rmse, 100*rmse / arclength))
        print("Perceptual derivative: %0.5f +/- %0.5f" % (arclength, rmse))
        ax.set_ylim(-delta_ymax(-local_derivs), delta_ymax(local_derivs))
        ax.get_xaxis().set_visible(False)

        ax = axes['cmap-greyscale']
        _show_cmap(ax, to_greyscale(RGB))
        ax.set_title("Black-and-white printed")
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)

        ax = axes['lightness-deltas']
        ax.axhline(0, linestyle="--", color="grey")
        lightness_deltas = np.diff(Jpapbp[:, 0])
        lightness_derivs = (N-1)*lightness_deltas

        ax.plot(x[1:], lightness_derivs)
        title(ax, "Perceptual lightness derivative")
        lightness_arclength = np.sum(np.abs(lightness_deltas))
        lightness_rmse = np.std(lightness_derivs)
        label(ax,
              "Length: %0.1f\nRMS deviation from flat: %0.1f (%0.1f%%)"
              % (lightness_arclength, lightness_rmse,
                 100*lightness_rmse / lightness_arclength))
        print("Perceptual lightness derivative: %0.5f +/- %0.5f"
              % (lightness_arclength, lightness_rmse))

        ax.set_ylim(-delta_ymax(-lightness_derivs),
                    delta_ymax(lightness_derivs))
        ax.get_xaxis().set_visible(False)

        # ax = axes['lightness']
        # ax.plot(x, ciecam02.J)
        # label(ax, "Lightness (J)")
        # ax.set_ylim(0, 105)

        # ax = axes['colourfulness']
        # ax.plot(x, ciecam02.M)
        # label(ax, "Colourfulness (M)")

        # ax = axes['hue']
        # ax.plot(x, ciecam02.h)
        # label(ax, "Hue angle (h)")
        # ax.set_ylim(0, 360)

        def anom(ax, converter, name):
            _show_cmap(ax, np.clip(converter(RGB), 0, 1))
            label(ax, name)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

        anom(axes['deuteranomaly'],
             _deuter50_to_sRGB1,
             "Moderate deuteranomaly")
        anom(axes['deuteranopia'],
             _deuter100_to_sRGB1,
             "Complete deuteranopia")

        anom(axes['protanomaly'],
             _prot50_to_sRGB1,
             "Moderate protanomaly")
        anom(axes['protanopia'],
             _prot100_to_sRGB1,
             "Complete protanopia")

        ax = axes['gamut']
        ax.plot(Jpapbp[:, 1], Jpapbp[:, 2], Jpapbp[:, 0])
        Jpapbp_dots = self._sRGB1_to_uniform(RGB_dots)
        ax.scatter(Jpapbp_dots[:, 1],
                   Jpapbp_dots[:, 2],
                   Jpapbp_dots[:, 0],
                   c=RGB_dots[:, :],
                   s=80)

        # Draw a wireframe indicating the sRGB gamut
        self.gamut_patch = sRGB_gamut_patch(uniform_space)
        # That function returns a patch where each face is colored to match
        # the represented colors. For present purposes we want something
        # less... colorful.
        self.gamut_patch.set_facecolor([0.5, 0.5, 0.5, 0.1])
        self.gamut_patch.set_edgecolor([0.2, 0.2, 0.2, 0.1])
        ax.add_collection3d(self.gamut_patch)
        self.gamut_patch.set_visible(show_gamut)

        ax.view_init(elev=75, azim=-75)

        _setup_Jpapbp_axis(ax)

        images = []
        image_kwargs = []
        example_dir = os.path.join(os.path.dirname(__file__), "examples")

        if(cmtype in ('diverging', 'cyclic')):
            # Adapted from
            # https://github.com/endolith/bipolar-colormap/blob/master/bipolar.py
            X, Y = np.meshgrid(np.linspace(-2.5, 2.5, int(600/(327/468))),
                               np.linspace(-2, 2, 600))
            z = (1-X/2+X**5+Y**3)*np.exp(-X**2-Y**2)
            images.append(z)
            image_kwargs.append({
                'norm': TwoSlopeNorm(0)})
        else:
            images.append(
                np.loadtxt(
                    os.path.join(example_dir,
                                 "st-helens_before-modified_cropped.txt.gz"),
                    dtype=int))
            image_kwargs.append({})

        # Adapted from
        # http://matplotlib.org/mpl_examples/images_contours_and_fields/pcolormesh_levels.py
        dx = dy = 0.05
        y, x = np.mgrid[-5:5+dy:dy, -5:10+dx:dx]
        z = np.sin(x)**10+np.cos(10+y*x)+np.cos(x)+0.2*y+0.1*x
        images.append(z)
        image_kwargs.append({})

        # Peter Kovesi's colormap test image at
        # http://peterkovesi.com/projects/colourmaps/colourmaptest.tif

        images.append(np.load(os.path.join(example_dir, "colourmaptest.npy")))

        image_kwargs.append({})

        def _deuter_transform(RGBA):
            # clipping, alpha handling
            RGB = RGBA[..., :3]
            RGB = np.clip(_deuter50_to_sRGB1(RGB), 0, 1)
            return np.concatenate((RGB, RGBA[..., 3:]), axis=-1)
        deuter_cm = TransformedCMap(_deuter_transform, cm)

        for i, (image, kwargs) in enumerate(zip(images, image_kwargs)):
            ax = axes['image%i' % (i,)]
            ax.imshow(image, cmap=cm, **kwargs)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

            ax_cb = axes['image%i-cb' % (i,)]
            ax_cb.imshow(image, cmap=deuter_cm, **kwargs)
            ax_cb.get_xaxis().set_visible(False)
            ax_cb.get_yaxis().set_visible(False)

        axes['image0'].set_title("Sample images")
        axes['image0-cb'].set_title("Moderate deuter.")
        self.axes = axes

    def toggle_gamut(self):
        self.gamut_patch.set_visible(not self.gamut_patch.get_visible())

    def save_figure(self, path):
        self.figure.savefig(path)


def sRGB_gamut_patch(uniform_space, resolution=20):
    step = 1.0 / resolution
    sRGB_quads = []
    sRGB_values = []
    # each entry in 'quads' is a 4x3 array where each row contains the
    # coordinates of a corner point
    for fixed in 0, 1:
        for i in range(resolution):
            for j in range(resolution):
                # R quad
                sRGB_quads.append([[fixed, i * step, j * step],
                                   [fixed, (i+1) * step, j * step],
                                   [fixed, (i+1) * step, (j+1) * step],
                                   [fixed, i * step, (j+1) * step]])
                sRGB_values.append((fixed, (i + 0.5) * step, (j + 0.5) * step,
                                    1))
                # G quad
                sRGB_quads.append([[i * step, fixed, j * step],
                                   [(i+1) * step, fixed, j * step],
                                   [(i+1) * step, fixed, (j+1) * step],
                                   [i * step, fixed, (j+1) * step]])
                sRGB_values.append(((i + 0.5) * step, fixed, (j + 0.5) * step,
                                    1))
                # B quad
                sRGB_quads.append([[i * step, j * step, fixed],
                                   [(i+1) * step, j * step, fixed],
                                   [(i+1) * step, (j+1) * step, fixed],
                                   [i * step, (j+1) * step, fixed]])
                sRGB_values.append(((i + 0.5) * step, (j + 0.5) * step, fixed,
                                    1))
    sRGB_quads = np.asarray(sRGB_quads)
    # work around colorspace transform bugginess in handling high-dim
    # arrays
    sRGB_quads_2d = sRGB_quads.reshape((-1, 3))
    Jpapbp_quads_2d = cspace_convert(sRGB_quads_2d, "sRGB1", uniform_space)
    Jpapbp_quads = Jpapbp_quads_2d.reshape((-1, 4, 3))
    gamut_patch = mpl_toolkits.mplot3d.art3d.Poly3DCollection(
        Jpapbp_quads[:, :, [1, 2, 0]])
    gamut_patch.set_facecolor(sRGB_values)
    gamut_patch.set_edgecolor(sRGB_values)
    return gamut_patch


def sRGB_gamut_Jp_slice(Jp, uniform_space,
                        ap_lim=(-50, 50), bp_lim=(-50, 50), resolution=256):
    bp_grid, ap_grid = np.mgrid[bp_lim[0]:bp_lim[1]:resolution*1j,
                                ap_lim[0]:ap_lim[1]:resolution*1j]
    Jp_grid = Jp * np.ones((resolution, resolution))
    Jpapbp = np.concatenate((Jp_grid[:, :, np.newaxis],
                             ap_grid[:, :, np.newaxis],
                             bp_grid[:, :, np.newaxis]),
                            axis=2)
    sRGB = cspace_convert(Jpapbp, uniform_space, "sRGB1")
    sRGBA = np.concatenate((sRGB, np.ones(sRGB.shape[:2] + (1,))),
                           axis=2)
    sRGBA[np.any((sRGB < 0) | (sRGB > 1), axis=-1)] = [0, 0, 0, 0]
    return sRGBA


def draw_pure_hue_angles(ax):
    # Pure hue angles from CIECAM-02
    for color, angle in [("r", 20.14),
                         ("y", 90.00),
                         ("g", 164.25),
                         ("b", 237.53)]:
        x = np.cos(np.deg2rad(angle))
        y = np.sin(np.deg2rad(angle))
        ax.plot([0, x * 1000], [0, y * 1000], color + "--")


def draw_sRGB_gamut_Jp_slice(ax, Jp, uniform_space,
                             ap_lim=(-50, 50), bp_lim=(-50, 50),
                             **kwargs):
    sRGB = sRGB_gamut_Jp_slice(Jp, uniform_space,
                               ap_lim=ap_lim, bp_lim=bp_lim, **kwargs)
    im = ax.imshow(sRGB, aspect="equal",
                   extent=ap_lim + bp_lim, origin="lower")
    draw_pure_hue_angles(ax)
    ax.set_xlim(ap_lim)
    ax.set_ylim(bp_lim)
    return im

# def sRGB_gamut_J_slice(J,
#                        ap_lim=(-50, 50), bp_lim=(-50, 50), resolution=200):
#     a_grid, b_grid = np.mgrid[ap_lim[0] : ap_lim[1] : resolution * 1j,
#                               bp_lim[0] : bp_lim[1] : resolution * 1j]
#     J_grid = J * np.ones((resolution, resolution))
#     h = np.rad2deg(np.arctan2(b_grid, a_grid))
#     M = np.hypot(a_grid, b_grid)
#     XYZ = ViewingConditions.sRGB.CIECAM02_to_XYZ(J=J_grid, M=M, h=h)
#     sRGB = XYZ_to_sRGB(XYZ)
#     sRGB[np.any((sRGB < 0) | (sRGB > 1), axis=-1)] = np.nan
#     return sRGB


def _viscm_editor_axes(fig):
    grid = GridSpec(1, 2,
                    width_ratios=[9, 1],
                    height_ratios=[50])
    axes = {'bezier': grid[0, 0],
            'cm': grid[0, 1]}

    axes = dict([(key, fig.add_subplot(value))
                 for (key, value) in axes.items()])
    return axes


class viscm_editor(object):
    def __init__(self, figure=None, uniform_space="CAM02-UCS",
                 min_Jp=15, max_Jp=95, xp=None, yp=None, cmtype='sequential',
                 fixed=-1, name="new cm", method="CatmulClark"):
        if figure is None:
            figure = plt.figure()
        self.cmtype = cmtype
        self.method = method
        self._uniform_space = uniform_space
        self.name = name
        self.figure = figure
        axes = _viscm_editor_axes(self.figure)
        self.min_Jp = min_Jp
        self.max_Jp = max_Jp
        self.fixed = fixed
        if self.cmtype in ["diverging", "diverging-continuous"] and xp is None:
            self.fixed = 4
        elif self.cmtype in ["cyclic"] and xp is None:
            self.fixed = [0, 4]
        if xp is None or yp is None:
            if method == "Bezier":
                xp = {'sequential': [-2.0591553836234482, 59.377014829142524,
                                     43.552546744036135, 4.7670857511283202,
                                     -9.5059638942617539],
                      "diverging": [
                          -9, -15, 43, 30, 0, -20, -30, 20, 1],
                      "diverging-continuous": [
                          -9, -15, 43, 30, 0, -20, -30, 20, 1],
                      }[cmtype]
                yp = {'sequential': [-25.664893617021221, -21.941489361702082,
                                     38.874113475177353, 20.567375886524871,
                                     32.047872340425585],
                      "diverging": [
                          -5, 20, 20, -21, 0, 21, -38, -20, -5],
                      "diverging-continuous": [
                          -5, 20, 20, -21, 0, 21, -38, -20, -5]
                      }[cmtype]
            if method == "CatmulClark":
                xp = {'sequential': [-2, 20, 23, 5, -9],
                      "diverging": [-9, -15, -10, 0, 0, 5, 10, 15, 2],
                      "diverging-continuous": [-9, -5, -1, 0, 0, 5, 10, 15, 2],
                      }[cmtype]
                yp = {'sequential': [-25, -21, 18, 10, 12],
                      "diverging": [-5, -8, -20, -10, 0, 2, 8, 15, 5],
                      "diverging-continuous": [
                          -5, -8, -20, -10, 0, 2, 8, 15, 5]
                      }[cmtype]
        xy_lim = {"Bezier": (-100, 100),
                  "CatmulClark": (-50, 50)}[self.method]

        BezierModel, startJp = {
            'sequential': (SingleBezierCurveModel, 0.5),
            "diverging": (TwoBezierCurveModel, 0.75),
            "diverging-continuous": (TwoBezierCurveModel, 0.5),
            "cyclic": (TwoBezierCurveModel, 0.75)
            }[cmtype]

        self.control_point_model = ControlPointModel(xp, yp, cmtype,
                                                     fixed=self.fixed)
        self.bezier_model = BezierModel(self.control_point_model, self.method)
        axes['bezier'].add_line(self.bezier_model.bezier_curve)
        self.cmap_model = BezierCMapModel(self.bezier_model,
                                          self.min_Jp,
                                          self.max_Jp,
                                          uniform_space,
                                          cmtype=cmtype)

        self.highlight_point_model = HighlightPointModel(self.cmap_model,
                                                         startJp)
        self.highlight_point_model1 = None

        self.bezier_builder = ControlPointBuilder(axes['bezier'],
                                                  self.control_point_model,
                                                  self.cmap_model)

        self.bezier_gamut_viewer = GamutViewer2D(axes['bezier'],
                                                 self.highlight_point_model,
                                                 uniform_space,
                                                 )

        self.bezier_highlight_point_view = HighlightPoint2DView(
            axes['bezier'], self.highlight_point_model)
        if cmtype in ("diverging", 'cyclic'):
            self.highlight_point_model1 = HighlightPointModel(
                self.cmap_model, 1 - startJp)
            self.bezier_highlight_point_view1 = HighlightPoint2DView(
                axes['bezier'], self.highlight_point_model1)

        # draw_pure_hue_angles(axes['bezier'])
        axes['bezier'].set_xlim(*xy_lim)
        axes['bezier'].set_ylim(*xy_lim)

        self.cmap_view = CMapView(axes['cm'], self.cmap_model)
        self.cmap_highlighter = HighlightPointBuilder(
            axes['cm'],
            self.highlight_point_model,
            self.highlight_point_model1)
        self.axes = axes

    def save_colormap(self, filepath):
        with open(filepath, 'w') as f:
            xp, yp, fixed = self.control_point_model.get_control_points()
            rgb, _ = self.cmap_model.get_sRGB()
            if np.all(np.isfinite(rgb)):
                hex_blob = ""
                for color in rgb:
                    for component in color:
                        hex_blob += "%02x" % (int(round(component * 255)))
            else:
                hex_blob = "N/A"
            usage_hints = ["red-green-colorblind-safe", "greyscale-safe"]
            if self.cmtype == "diverging":
                usage_hints.append("diverging")
            elif self.cmtype == 'sequential':
                usage_hints.append("sequential")
            elif self.cmtype == "cyclic":
                usage_hints.append("cyclic")
            xp, yp, fixed = self.control_point_model.get_control_points()
            extensions = {"min_Jp": self.min_Jp,
                          "max_Jp": self.max_Jp,
                          "xp": xp,
                          "yp": yp,
                          "fixed": fixed,
                          "filter_k": 100,
                          "cmtype": self.cmtype,
                          "uniform_colorspace": self._uniform_space,
                          "spline_method": self.method
                          }
            json.dump({"content-type": (
                           "application/vnd.matplotlib.colormap-v1+json"),
                       "name": self.name,
                       "license": (
                           "http://creativecommons.org/publicdomain/zero/1.0"),
                       "usage-hints": usage_hints,
                       "colorspace": "sRGB",
                       "domain": "continuous",
                       "colors": hex_blob,
                       "extensions": {
                           "https://matplotlib.org/viscm": extensions}
                       }, f, indent=4)
        print("Saved")

    def export_py(self, filepath):
        import textwrap
        template = textwrap.dedent('''
        from matplotlib.colors import ListedColormap

        cm_type = "{type}"

        cm_data = {array_list}
        test_cm = ListedColormap(cm_data, name="{name}")
        ''')
        rgb, _ = self.cmap_model.get_sRGB()
        if not np.all(np.isfinite(rgb)):
            QW.QMessageBox.warning(None, "Warning",
                                   "Cannot export invalid colormap!")
            return
        array_list = np.array2string(rgb, max_line_width=79,
                                     prefix='cm_data = ',
                                     separator=', ', threshold=rgb.size)
        with open(filepath, 'w') as f:
            f.write(template.format(**dict(array_list=array_list,
                                           type=self.cmtype, name=self.name)))

    def show_viscm(self):
        cm = ListedColormap(self.cmap_model.get_sRGB()[0],
                            name=self.name)

        return cm

    def _jp_update(self, minval, maxval):
        if minval >= 0 and minval <= 100 and maxval >= 0 and maxval <= 100:
            self.min_Jp = minval
            self.max_Jp = maxval
            self.cmap_model.set_Jp_minmax(self.min_Jp, self.max_Jp)


class BezierCMapModel(object):
    def __init__(self, bezier_model, min_Jp, max_Jp, uniform_space,
                 cmtype='sequential'):
        self.bezier_model = bezier_model
        self.min_Jp = min_Jp
        self.max_Jp = max_Jp
        self.cmtype = cmtype
        self.trigger = Trigger()
        self.Jp_minmax_trigger = Trigger()
        self.Jp_minmax_trigger.add_callback(self.trigger.fire)
        self.uniform_to_sRGB1 = cspace_converter(uniform_space, "sRGB1")
        self.bezier_model.trigger.add_callback(self.trigger.fire)

    def set_Jp_minmax(self, min_Jp, max_Jp):
        self.min_Jp = min_Jp
        self.max_Jp = max_Jp
        self.Jp_minmax_trigger.fire()

    def get_Jpapbp_at_point(self, point):
        from scipy.interpolate import interp1d
        Jp, ap, bp = self.get_Jpapbp()
        Jp, ap, bp = interp1d(np.linspace(0, 1, Jp.size),
                              np.array([Jp, ap, bp]))(point)
        return Jp, ap, bp

    def get_Jpapbp(self):
        at = np.linspace(0, 1, {'sequential': 256,
                                'diverging': 511,
                                'cyclic': 510}[self.cmtype],
                         (self.cmtype != 'cyclic'))
        ap, bp = self.bezier_model.get_bezier_points_at(at)
        if self.cmtype != 'sequential':
            at = np.abs(1-2*at)
        Jp = (self.max_Jp - self.min_Jp) * at + self.min_Jp
        return Jp, ap, bp

    def get_sRGB(self):
        # Return sRGB and out-of-gamut mask
        Jp, ap, bp = self.get_Jpapbp()
        sRGB = self.uniform_to_sRGB1(np.column_stack((Jp, ap, bp)))
        oog = np.any((sRGB > 1) | (sRGB < 0), axis=-1)
        sRGB[oog, :] = np.nan
        return sRGB, oog


class CMapView(object):
    def __init__(self, ax, cmap_model):
        self.ax = ax
        self.cmap_model = cmap_model

        rgb_display, oog_display = self._drawable_arrays()
        self.image = self.ax.imshow(rgb_display, extent=(0, 0.2, 0, 1),
                                    origin="lower")
        self.gamut_alert_image = self.ax.imshow(oog_display,
                                                extent=(0.05, 0.15, 0, 1),
                                                origin="lower")
        self.ax.set_xlim(0, 0.2)
        self.ax.set_ylim(0, 1)
        self.ax.get_xaxis().set_visible(False)

        self.cmap_model.trigger.add_callback(self._refresh)

    def _drawable_arrays(self):
        rgb, oog = self.cmap_model.get_sRGB()
        rgb_display = rgb[:, np.newaxis, :]
        oog_display = np.empty((rgb.shape[0], 1, 4))
        oog_display[...] = [0, 0, 0, 0]
        oog_display[oog, :, :] = [0, 1, 1, 1]
        return rgb_display, oog_display

    def _refresh(self):
        rgb_display, oog_display = self._drawable_arrays()
        self.image.set_data(rgb_display)
        self.gamut_alert_image.set_data(oog_display)


class HighlightPointModel(object):
    def __init__(self, cmap_model, point):
        self._cmap_model = cmap_model
        self._point = point
        self.trigger = Trigger()

        self._cmap_model.trigger.add_callback(self.trigger.fire)

    def get_point(self):
        return self._point

    def set_point(self, point):
        self._point = point
        self.trigger.fire()

    def get_Jpapbp(self):
        return self._cmap_model.get_Jpapbp_at_point(self._point)


class HighlightPointBuilder(object):
    def __init__(self, ax, highlight_point_model_a, highlight_point_model_b):
        self.ax = ax
        self.highlight_point_model_b = highlight_point_model_b
        self.highlight_point_model_a = highlight_point_model_a

        self.canvas = self.ax.figure.canvas
        self._in_drag = False

        self.marker_line_a = self.ax.axhline(
            highlight_point_model_a.get_point(), linewidth=3, color="r")
        if self.highlight_point_model_b:
            self.marker_line_b = self.ax.axhline(
                highlight_point_model_b.get_point(), linewidth=3, color="r")

        self.canvas.mpl_connect("button_press_event", self._on_button_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event",
                                self._on_button_release)

        self.highlight_point_model_a.trigger.add_callback(self._refresh)
        if highlight_point_model_b:
            self.highlight_point_model_a.trigger.add_callback(self._refresh)

    def _on_button_press(self, event):
        if event.inaxes != self.ax:
            return
        if event.button != 1:
            return
        self._in_drag = True
        self.highlight_point_model_a.set_point(event.ydata)
        if self.highlight_point_model_b:
            self.highlight_point_model_b.set_point(1 - event.ydata)

    def _on_motion(self, event):
        if self._in_drag and event.ydata is not None:
            self.highlight_point_model_a.set_point(event.ydata)
            if self.highlight_point_model_b:
                self.highlight_point_model_b.set_point(1 - event.ydata)

    def _on_button_release(self, event):
        if event.button != 1:
            return
        self._in_drag = False

    def _refresh(self):
        point = self.highlight_point_model_a.get_point()
        self.marker_line_a.set_data([0, 1], [point, point])
        if self.highlight_point_model_b:
            self.marker_line_b.set_data([0, 1], [1 - point, 1 - point])
        self.canvas.draw()


class GamutViewer2D(object):
    def __init__(self, ax, highlight_point_model, uniform_space,
                 ap_lim=(-50, 50), bp_lim=(-50, 50)):
        self.ax = ax
        self.highlight_point_model = highlight_point_model
        self.ap_lim = ap_lim
        self.bp_lim = bp_lim
        self.uniform_space = uniform_space

        self.bgcolors = {"light": (0.9, 0.9, 0.9),
                         "dark": (0.1, 0.1, 0.1)}
        # We want some hysteresis, so that there's no point where wiggling the
        # line back and forth causes background flickering.
        self.bgcolor_ranges = {"light": (0, 60), "dark": (40, 100)}
        self.bg_opposites = {"light": "dark", "dark": "light"}
        self.bg = "light"
        self.ax.set_facecolor(self.bgcolors[self.bg])

        self.image = self.ax.imshow([[[0, 0, 0]]], aspect="equal",
                                    extent=ap_lim + bp_lim,
                                    origin="lower")

        self.highlight_point_model.trigger.add_callback(self._refresh)

    def _refresh(self):
        Jp, _, _ = self.highlight_point_model.get_Jpapbp()
        low, high = self.bgcolor_ranges[self.bg]
        if not (low <= Jp <= high):
            self.bg = self.bg_opposites[self.bg]
            self.ax.set_facecolor(self.bgcolors[self.bg])
        sRGB = sRGB_gamut_Jp_slice(Jp, self.uniform_space,
                                   self.ap_lim, self.bp_lim)
        self.image.set_data(sRGB)


class HighlightPoint2DView(object):
    def __init__(self, ax, highlight_point_model):
        self.ax = ax
        self.highlight_point_model = highlight_point_model

        _, ap, bp = self.highlight_point_model.get_Jpapbp()
        self.marker = self.ax.plot([ap], [bp], "y.", mew=3)[0]

        self.highlight_point_model.trigger.add_callback(self._refresh)

    def _refresh(self):
        _, ap, bp = self.highlight_point_model.get_Jpapbp()
        self.marker.set_data([ap], [bp])
        self.ax.figure.canvas.draw()


# def loadpyfile(path):
#     is_native = True
#     cmtype = 'sequential'
#     method = "Bezier"
#     ns = {'__name__': '',
#           '__file__': os.path.basename(path),
#           }
#     with open(args.colormap) as f:
#         code = compile(f.read(),
#                         os.path.basename(args.colormap),
#                         'exec')
#         exec(code, globals(), ns)

#     params = ns.get('parameters', {})
#     if "min_JK" in params:
#         params["min_Jp"] = params.pop("min_JK")
#         params["max_Jp"] = params.pop("max_JK")
#     cmap = ns.get("test_cm", None)
#     return params, cmtype, cmap.name, cmap, is_native, method

class Colormap(object):
    def __init__(self, cmtype, method, uniform_space):
        self.can_edit = True
        self.params = {}
        self.cmtype = cmtype
        self.method = method
        self.name = None
        self.cmap = None
        self.uniform_space = uniform_space
        if self.uniform_space == "buggy-CAM02-UCS":
            self.uniform_space = buggy_CAM02UCS

    def load(self, path):
        self.path = path
        if os.path.isfile(path):
            _, extension = os.path.splitext(path)
            if extension == ".py":
                self.can_edit = True
                self.cmtype = 'sequential'
                self.method = "Bezier"
                ns = {'__name__': '',
                      '__file__': os.path.basename(self.path),
                      }
                with open(self.path) as f:
                    code = compile(f.read(),
                                   os.path.basename(self.path),
                                   'exec')
                    exec(code, globals(), ns)
                self.params = ns.get('parameters', {})
                if not self.params:
                    self.can_edit = False
                if "min_JK" in self.params:
                    self.params["min_Jp"] = self.params.pop("min_JK")
                    self.params["max_Jp"] = self.params.pop("max_JK")
                self.cmap = ns.get("test_cm", None)
                self.name = self.cmap.name
            elif extension == ".jscm":
                self.can_edit = False
                with open(self.path) as f:
                    data = json.loads(f.read())
                    self.name = data["name"]
                    # If extensions are available, load everything
                    if("extensions" in data and
                       "https://matplotlib.org/viscm" in data["extensions"]):
                        self.can_edit = True
                        self.params = {
                            k: v for k, v in data[
                                "extensions"][
                                    "https://matplotlib.org/viscm"].items()
                            if k in {"xp", "yp", "min_Jp", "max_Jp", "fixed",
                                     "uniform_space"}}
                        self.params["name"] = self.name
                        self.cmtype = data["extensions"][
                            "https://matplotlib.org/viscm"]["cmtype"]
                        self.cmtype = ('sequential' if self.cmtype == 'linear'
                                       else self.cmtype)
                        self.method = data["extensions"][
                            "https://matplotlib.org/viscm"]["spline_method"]
                        self.uniform_space = data["extensions"][
                            "https://matplotlib.org/viscm"][
                                "uniform_colorspace"]

                        # As original method uses real colors instead of floats
                        # which obviously have rounding errors, use params
                        # to create an editor and use that to obtain cmap
                        v = viscm_editor(uniform_space=self.uniform_space,
                                         cmtype=self.cmtype,
                                         method=self.method,
                                         **self.params)
                        self.cmap = v.show_viscm()
                    # If extensions do not exist, use original method
                    # This however suffers from the normal rounding errors
                    else:
                        colors = data["colors"]
                        if(colors != "N/A"):
                            colors = [colors[i:i+6]
                                      for i in range(0, len(colors), 6)]
                            colors = [[int(c[2*i:2*i+2], 16)/255
                                       for i in range(3)] for c in colors]
                            self.cmap = ListedColormap(colors, self.name)
                        else:
                            sys.exit("Cannot load invalid colormap without "
                                     "proper extensions!")
            elif extension == '.txt':
                self.can_edit = False
                rgb = np.genfromtxt(path, dtype=None, comments='//',
                                    encoding=None)
                colorlist = rgb.tolist()
                self.cmap = ListedColormap(
                    colorlist, os.path.basename(path), N=len(colorlist))
                self.name = self.cmap.name

            else:
                sys.exit("Unsupported filetype")
        else:
            self.can_edit = False
            self.cmap = lookup_colormap_by_name(path)
            self.name = path


def main(argv=None):
    import argparse
    import sys
    if argv is None:
        argv = sys.argv[1:]
    # Usage:
    #   python -m viscm
    #   python -m viscm edit
    #   python -m viscm edit <file.py>
    #      (file.py must define some appropriate globals)
    #   python -m viscm view <file.py>
    #      (file.py must define a global named "test_cm")
    #   python -m viscm view "matplotlib builtin colormap"
    #   python -m viscm view --save=foo.png ...

    parser = argparse.ArgumentParser(
        prog="python -m viscm",
        description="A colormap tool.",
    )
    parser.add_argument("action", metavar="ACTION",
                        help="'edit' or 'view' (or 'show', same as 'view')",
                        choices=["edit", "view", "show"],
                        default="edit",
                        nargs="?")
    parser.add_argument("colormap", metavar="COLORMAP",
                        default=None,
                        help="A .json file saved from the editor, or "
                             "the name of a matplotlib builtin colormap",
                        nargs="?")
    parser.add_argument("--uniform-space", metavar="SPACE",
                        default="CAM02-UCS",
                        dest="uniform_space",
                        help="The perceptually uniform space to use. Usually "
                        "you should leave this alone. You can pass 'CIELab' "
                        "if you're curious how uniform some colormap is in "
                        "CIELab space. You can pass 'buggy-CAM02-UCS' if "
                        "you're trying to reproduce the matplotlib colormaps "
                        "(which turn out to have had a small bug in the "
                        "assumed sRGB viewing conditions) from their bezier "
                        "curves.")
    parser.add_argument("-t", "--type", type=str,
                        default="sequential",
                        choices=["sequential", "diverging", 'cyclic'],
                        help=("Choose a colormap type. Supported options are "
                              "'sequential', 'diverging', and 'cyclic'"))
    parser.add_argument("-m", "--method", type=str,
                        default="CatmulClark", choices=["Bezier",
                                                        "CatmulClark"],
                        help=("Choose a spline construction method. "
                              "'CatmulClark' is the default, but you may "
                              "choose the legacy option 'Bezier'"))
    parser.add_argument("--save", metavar="FILE",
                        default=None,
                        help="Immediately save visualization to a file "
                             "(view-mode only).")
    parser.add_argument("--quit", default=False, action="store_true",
                        help="Quit immediately after starting "
                             "(useful with --save).")
    args = parser.parse_args(argv)

    cm = Colormap(args.type, args.method, args.uniform_space)
    app = QW.QApplication([])

    if args.colormap:
        cm.load(args.colormap)

    # Easter egg! I keep typing 'show' instead of 'view' so accept both
    if args.action in ("view", "show"):
        if cm is None:
            sys.exit("Please specify a colormap")
        fig = plt.figure()
        figureCanvas = FigureCanvas(fig)
        v = viscm(cm.cmap, name=cm.name, figure=fig,
                  uniform_space=cm.uniform_space)
        mainwindow = ViewerWindow(figureCanvas, v, cm.name)
        if args.save is not None:
            v.figure.set_size_inches(20, 12)
            v.figure.savefig(args.save)
    elif args.action == "edit":
        if not cm.can_edit:
            sys.exit("Sorry, I don't know how to edit the specified colormap")
        # Hold a reference so it doesn't get GC'ed
        fig = plt.figure()
        figureCanvas = FigureCanvas(fig)
        v = viscm_editor(figure=fig, uniform_space=cm.uniform_space,
                         cmtype=cm.cmtype, method=cm.method, **cm.params)
        mainwindow = EditorWindow(figureCanvas, v)
    else:
        raise RuntimeError("can't happen")

    if args.quit:
        sys.exit()

    figureCanvas.setSizePolicy(QW.QSizePolicy.Expanding,
                               QW.QSizePolicy.Expanding)
    figureCanvas.updateGeometry()

    mainwindow.resize(800, 600)
    mainwindow.show()

    # PyQt messes up signal handling by default. Python signal handlers (e.g.,
    # the default handler for SIGINT that raises KeyboardInterrupt) can only
    # run when we enter the Python interpreter, which doesn't happen while
    # idling in the Qt mainloop. (Unless we register a timer to poll
    # explicitly.) So here we unregister Python's default signal handler and
    # replace it with... the *operating system's* default signal handler, so
    # instead of a KeyboardInterrupt our process just exits.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app.exec_()


def about():
    QW.QMessageBox.about(None, "VISCM",
                         ("Copyright (C) 2015-2016 Nathaniel Smith\n"
                          "Copyright (C) 2015-2016 Stéfan van der Walt\n"
                          "Copyright (C) 2016 Hankun Zhao\n"
                          "Copyright (C) 2020-2021 Ellert van der Velden"))


class ViewerWindow(QW.QMainWindow):
    def __init__(self, figurecanvas, viscm, cmapname, parent=None):
        QW.QMainWindow.__init__(self, parent)
        self.setAttribute(QC.Qt.WA_DeleteOnClose)
        self.main_widget = QW.QWidget(self)
        self.cmapname = cmapname

        file_menu = QW.QMenu('&File', self)
        file_menu.addAction('&Save', self.save,
                            QC.Qt.CTRL + QC.Qt.Key_S)
        file_menu.addAction('&Quit', self.fileQuit,
                            QC.Qt.CTRL + QC.Qt.Key_Q)

        options_menu = QW.QMenu('&Options', self)
        options_menu.addAction('&Toggle Gamut', self.toggle_gamut,
                               QC.Qt.CTRL + QC.Qt.Key_G)

        help_menu = QW.QMenu('&Help', self)
        help_menu.addAction('&About', about)

        self.menuBar().addMenu(file_menu)
        self.menuBar().addMenu(options_menu)
        self.menuBar().addMenu(help_menu)
        self.setWindowTitle("VISCM Editing : " + cmapname)

        self.viscm = viscm
        self.figurecanvas = figurecanvas

        v = QW.QVBoxLayout(self.main_widget)
        v.addWidget(figurecanvas)

        self.main_widget.setFocus()
        self.setCentralWidget(self.main_widget)

    def toggle_gamut(self):
        self.viscm.toggle_gamut()
        self.figurecanvas.draw()

    def fileQuit(self):
        self.close()

    def closeEvent(self, ce):
        self.fileQuit()

    def save(self):
        fileName, _ = QW.QFileDialog.getSaveFileName(
            caption="Save file",
            directory=self.cmapname + ".png",
            filter="Image Files (*.png *.jpg *.bmp)")
        if fileName:
            self.viscm.save_figure(fileName)


class EditorWindow(QW.QMainWindow):
    def __init__(self, figurecanvas, viscm_editor, parent=None):
        QW.QMainWindow.__init__(self, parent)
        self.setAttribute(QC.Qt.WA_DeleteOnClose)
        self.viscm_editor = viscm_editor

        file_menu = QW.QMenu('&File', self)
        file_menu.addAction('&Save as...', self.save,
                            QC.Qt.CTRL + QC.Qt.Key_S)
        file_menu.addAction("&Export .py", self.export)
        file_menu.addAction('&Quit', self.fileQuit,
                            QC.Qt.CTRL + QC.Qt.Key_Q)

        options_menu = QW.QMenu('&Options', self)
        options_menu.addAction('&Load in Viewer', self.loadviewer,
                               QC.Qt.CTRL + QC.Qt.Key_V)

        help_menu = QW.QMenu('&Help', self)
        help_menu.addAction('&About', about)

        self.menuBar().addMenu(file_menu)
        self.menuBar().addMenu(options_menu)
        self.menuBar().addMenu(help_menu)
        self.setWindowTitle("VISCM Editing : " + viscm_editor.name)

        self.main_widget = QW.QWidget(self)

        self.fixed_widget = QW.QCheckBox("Fixed?")
        self.fixed_widget.setChecked(True)
        self.fixed_widget.toggled.connect(self.set_fixed_movable)

        self.min_num = QW.QDoubleSpinBox()
        self.min_num.setDecimals(8)
        self.min_num.setRange(0, 99.99871678)
        self.min_num.setValue(viscm_editor.min_Jp)
        self.min_num.valueChanged.connect(self.updatejp)

        self.max_num = QW.QDoubleSpinBox()
        self.max_num.setDecimals(8)
        self.max_num.setRange(0, 99.99871678)
        self.max_num.setValue(viscm_editor.max_Jp)
        self.max_num.valueChanged.connect(self.updatejp)

        # Create options layout for the bottom of the viewer
        options_layout = GL.QHBoxLayout()

        # Create layout for setting the colormap independent options
        options_layoutL = QW.QFormLayout()
        options_layout.addLayout(options_layoutL)
        options_layout.addSeparator()

        # Add colormap independent options
        # Cmap type box
        cmap_type_box = GW.QComboBox()
        cmap_type_box.addItems(['Sequential', 'Diverging', 'Cyclic'])
        set_box_value(cmap_type_box, viscm_editor.cmtype.capitalize())
        options_layoutL.addRow("Colormap type: ", cmap_type_box)
        self.cmap_type_box = cmap_type_box

        # X-axis limits
        x_lim_box = GW.DualSpinBox(sep='X')
        x_lims = self.viscm_editor.axes['bezier'].get_xlim()
        x_lim_box[0].setRange(-250, x_lims[0])
        x_lim_box[1].setRange(x_lims[1], 250)
        set_box_value(x_lim_box, x_lims)
        get_modified_signal(x_lim_box).connect(
            self.viscm_editor.axes['bezier'].set_xlim)
        get_modified_signal(x_lim_box).connect(figurecanvas.draw)
        options_layoutL.addRow("X-axis limits: ", x_lim_box)

        # Y-axis limits
        y_lim_box = GW.DualSpinBox(sep='X')
        y_lims = self.viscm_editor.axes['bezier'].get_ylim()
        y_lim_box[0].setRange(-250, y_lims[0])
        y_lim_box[1].setRange(y_lims[1], 250)
        set_box_value(y_lim_box, y_lims)
        get_modified_signal(y_lim_box).connect(
            self.viscm_editor.axes['bezier'].set_ylim)
        get_modified_signal(y_lim_box).connect(figurecanvas.draw)
        options_layoutL.addRow("Y-axis limits: ", y_lim_box)

        # Create layout for setting the colormap dependent options
        options_layoutR = QW.QFormLayout()
        options_layout.addLayout(options_layoutR)

        # Add colormap dependent options
        if viscm_editor.cmtype in ('diverging', 'cyclic'):
            options_layoutR.addRow("Central point: ", self.fixed_widget)
        options_layoutR.addRow("Jp_0: ", self.min_num)
        options_layoutR.addRow("Jp_1: ", self.max_num)

        figure_layout = QW.QHBoxLayout()
        figure_layout.addWidget(figurecanvas)

        mainlayout = QW.QVBoxLayout(self.main_widget)
        mainlayout.addLayout(figure_layout)
        mainlayout.addLayout(options_layout)

        self.moveAction = QW.QAction("Drag points", self)
        self.moveAction.triggered.connect(self.set_move_mode)
        self.moveAction.setCheckable(True)

        self.addAction = QW.QAction("Add points", self)
        self.addAction.triggered.connect(self.set_add_mode)
        self.addAction.setCheckable(True)

        self.removeAction = QW.QAction("Remove points", self)
        self.removeAction.triggered.connect(self.set_remove_mode)
        self.removeAction.setCheckable(True)

        self.swapAction = QW.QAction("Flip brightness", self)
        self.swapAction.triggered.connect(self.swapjp)
        renameAction = QW.QAction("Rename colormap", self)
        renameAction.triggered.connect(self.rename)

        saveAction = QW.QAction('Save as...', self)
        saveAction.triggered.connect(self.save)

        addL0_Action = QW.QAction("Add point at Jp=0", self)
        addL0_Action.setToolTip("Add point at lowest lightness possible. "
                                "For diverging colormaps, this replaces the "
                                "central fixed point.")
        addL0_Action.triggered.connect(
            lambda: self.viscm_editor.bezier_builder.add_point(0, 0))

        addL100_Action = QW.QAction("Add point at Jp=99.99871678", self)
        addL100_Action.setToolTip("Add point at highest lightness possible. "
                                  "For diverging colormaps, this replaces the "
                                  "central fixed point.")
        addL100_Action.triggered.connect(
            lambda: self.viscm_editor.bezier_builder.add_point(-1.91200895,
                                                               -1.15144878))

        self.toolbar = self.addToolBar('Tools')
        self.toolbar.addAction(self.moveAction)
        self.toolbar.addAction(self.addAction)
        self.toolbar.addAction(self.removeAction)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.swapAction)
        self.toolbar.addSeparator()
        self.toolbar.addAction(renameAction)
        self.toolbar.addAction(saveAction)
        self.toolbar.addSeparator()
        self.toolbar.addAction(addL0_Action)
        self.toolbar.addAction(addL100_Action)

        self.moveAction.setChecked(True)

        self.main_widget.setFocus()
        figurecanvas.setFocus()
        figurecanvas.setFocusPolicy(QC.Qt.StrongFocus)
        self.setCentralWidget(self.main_widget)

    def rename(self):
        name, ok = QW.QInputDialog.getText(
            self, "Rename your colormap", "Enter a name",
            text=self.viscm_editor.name)
        self.viscm_editor.name = name
        self.setWindowTitle("VISCM Editing : " + self.viscm_editor.name)

    def swapjp(self):
        jp1, jp2 = self.min_num.value(), self.max_num.value()
        self.min_num.setValue(jp2)
        self.max_num.setValue(jp1)
        self.updatejp()

    def updatejp(self):
        minval = self.min_num.value()
        maxval = self.max_num.value()
        self.viscm_editor._jp_update(minval, maxval)

    def set_move_mode(self):
        self.addAction.setChecked(False)
        self.removeAction.setChecked(False)
        self.viscm_editor.bezier_builder.mode = "move"

    def set_add_mode(self):
        self.moveAction.setChecked(False)
        self.removeAction.setChecked(False)
        self.viscm_editor.bezier_builder.mode = "add"

    def set_remove_mode(self):
        self.addAction.setChecked(False)
        self.moveAction.setChecked(False)
        self.viscm_editor.bezier_builder.mode = "remove"

    def set_fixed_movable(self, value):
        self.viscm_editor.control_point_model._fixed_point = value

    def export(self):
        fileName, _ = QW.QFileDialog.getSaveFileName(
            caption="Export file",
            directory=self.viscm_editor.name + ".py",
            filter=".py (*.py)")
        if fileName:
            self.viscm_editor.export_py(fileName)

    def fileQuit(self):
        self.close()

    def closeEvent(self, ce):
        self.fileQuit()

    def save(self):
        fileName, _ = QW.QFileDialog.getSaveFileName(
            caption="Save file",
            directory=self.viscm_editor.name + ".jscm",
            filter="JSCM Files (*.jscm)")
        if fileName:
            self.viscm_editor.save_colormap(fileName)

    def loadviewer(self):
        newfig = plt.figure()
        newcanvas = FigureCanvas(newfig)
        cm = self.viscm_editor.show_viscm()
        if not np.all(np.isfinite(cm.colors)):
            QW.QMessageBox.warning(self, "Warning",
                                   "Cannot show viewer for invalid colormap!")
            return
        v = viscm(cm, name=self.viscm_editor.name, figure=newfig)

        newcanvas.setSizePolicy(QW.QSizePolicy.Expanding,
                                QW.QSizePolicy.Expanding)
        newcanvas.updateGeometry()

        newwindow = ViewerWindow(newcanvas, v, self.viscm_editor.name,
                                 parent=self)
        newwindow.resize(800, 600)

        newwindow.show()


if __name__ == "__main__":
    main(sys.argv[1:])
