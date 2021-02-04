import math

import attr
import numpy as np

from nlisim.coordinates import Voxel
from nlisim.grid import RectangularGrid
from nlisim.module import ModuleState
from nlisim.modulesv2.geometry import GeometryState
from nlisim.modulesv2.macrophage import MacrophageCellData, MacrophageState
from nlisim.modulesv2.molecule import MoleculeModel
from nlisim.modulesv2.molecules import MoleculesState
from nlisim.modulesv2.phagocyte import PhagocyteStatus
from nlisim.random import rg
from nlisim.state import State
from nlisim.util import activation_function, turnover_rate


def molecule_grid_factory(self: 'TGFBState') -> np.ndarray:
    return np.zeros(shape=self.global_state.grid.shape, dtype=float)


@attr.s(kw_only=True, repr=False)
class TGFBState(ModuleState):
    grid: np.ndarray = attr.ib(default=attr.Factory(molecule_grid_factory, takes_self=True))
    half_life: float
    half_life_multiplier: float
    macrophage_secretion_rate: float
    macrophage_secretion_rate_unit_t: float
    k_d: float


class TGFB(MoleculeModel):
    """TGFB"""

    name = 'tgfb'
    StateClass = TGFBState

    def initialize(self, state: State) -> State:
        tgfb: TGFBState = state.tgfb

        # config file values
        tgfb.half_life = self.config.getfloat('half_life')
        tgfb.macrophage_secretion_rate = self.config.getfloat('macrophage_secretion_rate')
        tgfb.k_d = self.config.getfloat('k_d')

        # computed values
        tgfb.half_life_multiplier = 1 + math.log(0.5) / (tgfb.half_life / state.simulation.time_step_size)
        # time unit conversions
        tgfb.macrophage_secretion_rate_unit_t = tgfb.macrophage_secretion_rate * 60 * state.simulation.time_step_size

        return state

    def advance(self, state: State, previous_time: float) -> State:
        """Advance the state by a single time step."""
        tgfb: TGFBState = state.tgfb
        molecules: MoleculesState = state.molecules
        macrophage: MacrophageState = state.macrophage
        geometry: GeometryState = state.geometry
        grid: RectangularGrid = state.grid

        for macrophage_cell_index in macrophage.cells.alive():
            macrophage_cell: MacrophageCellData = macrophage.cells[macrophage_cell_index]
            macrophage_cell_voxel: Voxel = grid.get_voxel(macrophage_cell['point'])

            if macrophage_cell['status'] == PhagocyteStatus.INACTIVE:
                tgfb.grid[tuple(macrophage_cell_voxel)] += tgfb.macrophage_secretion_rate_unit_t
                if activation_function(x=tgfb.grid[tuple(macrophage_cell_voxel)],
                                       kd=tgfb.k_d,
                                       h=state.simulation.time_step_size / 60,
                                       volume=geometry.voxel_volume) > rg():
                    macrophage_cell['status_iteration'] = 0

            elif macrophage_cell['status'] not in {PhagocyteStatus.APOPTOTIC,
                                                   PhagocyteStatus.NECROTIC,
                                                   PhagocyteStatus.DEAD}:
                if activation_function(x=tgfb.grid[tuple(macrophage_cell_voxel)],
                                       kd=tgfb.k_d,
                                       h=state.simulation.time_step_size / 60,
                                       volume=geometry.voxel_volume) > rg():
                    macrophage_cell['status'] = PhagocyteStatus.INACTIVATING
                    macrophage_cell['status_iteration'] = 0  # Previously, was no reset of the status iteration

        # Degrade TGFB
        tgfb.grid *= tgfb.half_life_multiplier
        tgfb.grid *= turnover_rate(x_mol=np.array(1.0, dtype=np.float64),
                                   x_system_mol=0.0,
                                   base_turnover_rate=molecules.turnover_rate,
                                   rel_cyt_bind_unit_t=molecules.rel_cyt_bind_unit_t)

        return state
