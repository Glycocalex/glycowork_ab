# Changelog

## [1.8.1]
- fixed `deploy` action internally still relying on `nbdev2` (84134fb)

### glycan_data
#### loader
##### Added ✨

##### Changed 🔄
- Changed `human_macrophages_N_2024-11-28-625934` and `human_macrophages_O_2024-11-28-625934` glycomics datasets to `human_macrophages_N_2024_11_28_625934` and `human_macrophages_O_2024_11_28_625934`

##### Fixed 🐛

##### Deprecated ⚠️

### motif
#### analysis
##### Fixed 🐛
- Fixed column names slipping into column values when `motifs = True` combined with `transform = ALR` in `get_pca` (e802da1)
##### Changed 🔄
- Added distance matrix to beta diversity output

#### draw
##### Changed 🔄
- Improved branch spacing in `GlycoDraw` for highly branched glycans (6a673d0)

### network
#### biosynthesis
##### Added ✨
- Added `get_biosynthetic_coherence` function to estimate how well glycan abundances can be predicted from biosynthetic networks, to disentangle biosynthetic vs carrier variance (b7020fd)