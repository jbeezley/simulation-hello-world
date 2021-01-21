import attr
from attr import attrib, attrs
import numpy as np

from nlisim.coordinates import Voxel
from nlisim.grid import RectangularGrid
from nlisim.module import ModuleState
from nlisim.modulesv2.afumigatus import AfumigatusState, FungalForm
from nlisim.modulesv2.geometry import GeometryState
from nlisim.modulesv2.hemoglobin import HemoglobinState
from nlisim.modulesv2.hemolysin import HemolysinState
from nlisim.modulesv2.macrophage import MacrophageState
from nlisim.modulesv2.molecules import MoleculesState
from nlisim.modulesv2.phagocyte import PhagocyteModel
from nlisim.state import State
from nlisim.util import activation_function


# note: treating these a bit more like molecules than cells. hence the adaptation of molecule_grid_factory
def cell_grid_factory(self: 'ErythrocyteState') -> np.ndarray:
    return np.zeros(shape=self.global_state.grid.shape,
                    dtype=[('count', np.int),
                           ('hemoglobin', np.float),
                           ('hemorrhage', np.bool)])


@attrs(kw_only=True)
class ErythrocyteState(ModuleState):
    cells: np.ndarray = attrib(default=attr.Factory(cell_grid_factory, takes_self=True))
    kd_hemo: float
    max_erythrocyte_voxel: int
    hemoglobin_concentration: float
    pr_ma_phag_eryt: float


class ErythrocyteModel(PhagocyteModel):
    name = 'erythrocyte'
    StateClass = ErythrocyteState

    def initialize(self, state: State):
        erythrocyte: ErythrocyteState = state.erythrocyte
        grid: RectangularGrid = state.grid

        erythrocyte.kd_hemo = self.config.getfloat('kd_hemo')
        erythrocyte.max_erythrocyte_voxel = self.config.getint('max_erythrocyte_voxel')
        erythrocyte.hemoglobin_concentration = self.config.getfloat('hemoglobin_concentration')
        erythrocyte.pr_ma_phag_eryt = self.config.getfloat('pr_ma_phag_eryt')

        return state

    def advance(self, state: State, previous_time: float):
        erythrocyte: ErythrocyteState = state.erythrocyte
        molecules: MoleculesState = state.molecules
        hemoglobin: HemoglobinState = state.hemoglobin
        hemolysin: HemolysinState = state.hemolysin
        macrophage: MacrophageState = state.macrophage
        afumigatus: AfumigatusState = state.afumigatus
        geometry: GeometryState = state.geometry
        grid: RectangularGrid = state.grid

        shape = erythrocyte.cells['count'].shape

        # erythrocytes replenish themselves
        # TODO: avg? variable name improvement?
        avg = (1 - molecules.turnover_rate) * (1 - erythrocyte.cells['count'] / erythrocyte.max_erythrocyte_voxel)
        mask = avg > 0
        erythrocyte.cells['count'][mask] += np.random.poisson(avg[mask], avg[mask].shape)

        # ---------- interactions

        # uptake hemoglobin
        erythrocyte.cells['hemoglobin'] += hemoglobin.grid
        hemoglobin.grid.fill(0.0)

        # interact with hemolysin. pop goes the blood cell
        # TODO: avg? variable name improvement?
        avg = erythrocyte.cells['count'] * activation_function(x=hemolysin.grid,
                                                               kd=erythrocyte.kd_hemo,
                                                               h=state.simulation.time_step_size / 60,
                                                               volume=geometry.voxel_volume)
        num = np.minimum(np.random.poisson(avg, shape),
                         erythrocyte.cells['count'])
        erythrocyte.cells['hemoglobin'] += num * erythrocyte.hemoglobin_concentration
        erythrocyte.cells['count'] -= num

        # interact with Macrophage
        erythrocytes_to_hemorrhage = erythrocyte.cells['hemorrhage'] * \
                                     np.random.poisson(erythrocyte.pr_ma_phag_eryt * erythrocyte.cells['count'],
                                                       shape)
        # TODO: python for loop, possible performance issue
        zs, ys, xs = np.where(erythrocytes_to_hemorrhage > 0)
        for z, y, x in zip(zs, ys, xs):
            # TODO: make sure that these macrophages are alive!
            local_macrophages = erythrocyte.cells.get_cells_in_voxel(Voxel(x=x, y=y, z=z))
            num_local_macrophages = len(local_macrophages)
            for macrophage_index in local_macrophages:
                macrophage_cell = macrophage.cells[macrophage_index]
                # TODO: what's the 4 all about?
                macrophage_cell['iron_pool'] += 4 * \
                                                erythrocyte.hemoglobin_concentration * \
                                                erythrocytes_to_hemorrhage[z, y, x] / num_local_macrophages
        erythrocyte.cells['count'] -= erythrocytes_to_hemorrhage

        # interact with fungus
        for fungal_cell_index in afumigatus.cells.alive():
            fungal_cell = afumigatus.cells[fungal_cell_index]
            if fungal_cell['status'] == FungalForm.HYPHAE:
                fungal_voxel: Voxel = grid.get_voxel(fungal_cell['point'])
                erythrocyte.cells['hemorrhage'][fungal_voxel.z, fungal_voxel.y, fungal_voxel.x] = True

        return state