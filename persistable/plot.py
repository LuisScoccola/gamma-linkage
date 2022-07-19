# Authors: Luis Scoccola
# License: 3-clause BSD

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib import cm


def plot_hilbert_function(xs, ys, max_dim, dimensions, figsize=(8,4), colormap="binary"):
    cmap = cm.get_cmap(colormap)
    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(dimensions[::-1], cmap=cmap, aspect='auto', extent=[xs[0],xs[-1],ys[0],ys[-1]])
    ntics = 10
    bounds = list(range(0,max_dim,max_dim//ntics))
    norm = mpl.colors.BoundaryNorm(bounds, cmap.N, extend='max')
    fig.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap))
    im.set_clim(0,max_dim)
    ax.set_xlabel('distance scale')
    ax.set_ylabel('density threshold')
    return ax


# a combination of:
# https://stackoverflow.com/a/65604940/2171328
# https://stackoverflow.com/a/47166787/7128154
# https://matplotlib.org/3.3.3/api/collections_api.html#matplotlib.collections.PathCollection
# https://matplotlib.org/3.3.3/api/path_api.html#matplotlib.path.Path
# https://stackoverflow.com/questions/15876011/add-information-to-matplotlib-navigation-toolbar-status-bar
# https://stackoverflow.com/questions/36730261/matplotlib-path-contains-point
# https://stackoverflow.com/a/36335048/7128154
class StatusbarHoverManager:
    def __init__(self, ax):
        assert isinstance(ax, mpl.axes.Axes)

        def hover(event):
            if event.inaxes != ax:
                return
            info = "x={:.2f}, y={:.2f}".format(event.xdata, event.ydata)
            ax.format_coord = lambda x, y: info

        cid = ax.figure.canvas.mpl_connect("motion_notify_event", hover)

        self.ax = ax
        self.cid = cid
        self.artists = []
        self.labels = []
        #self.label = label

    def add_artist_labels(self, artist, label):
        if isinstance(artist, list):
            assert len(artist) == 1
            artist = artist[0]

        self.artists += [artist]
        self.labels += [label]

        def hover(event):
            if event.inaxes != self.ax:
                return
            # info = (str(self.xlabel)+'={:.3e}, ' + str(self.ylabel)+'={:.3e}').format(event.xdata, event.ydata)
            #info = self.label.format(event.xdata)
            info=""
            for aa, artist in enumerate(self.artists):
                cont, dct = artist.contains(event)
                if not cont:
                    continue
                inds = dct.get("ind")
                lbl = self.labels[aa]
                info += str(lbl) + ";    "

            self.ax.format_coord = lambda x, y: info

        self.ax.figure.canvas.mpl_disconnect(self.cid)
        self.cid = self.ax.figure.canvas.mpl_connect("motion_notify_event", hover)
