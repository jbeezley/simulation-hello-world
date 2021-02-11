import attr
import numpy as np

from nlisim.coordinates import Voxel
from nlisim.grid import RectangularGrid
from nlisim.module import ModuleState
from nlisim.modulesv2.geometry import GeometryState
from nlisim.modulesv2.molecules import MoleculeModel, MoleculesState
from nlisim.state import State
from nlisim.util import turnover_rate


def molecule_grid_factory(self: 'TAFCState') -> np.ndarray:
    # note the expansion to another axis to account for 0, 1, or 2 bound Fe's.
    return np.zeros(shape=self.global_state.grid.shape,
                    dtype=[('TAFC', np.float64),
                           ('TAFCBI', np.float64)])


@attr.s(kw_only=True, repr=False)
class TAFCState(ModuleState):
    grid: np.ndarray = attr.ib(default=attr.Factory(molecule_grid_factory, takes_self=True))
    k_m_tf_tafc: float
    tafc_up: float
    threshold: float
    tafc_qtty: float


class TAFC(MoleculeModel):
    # noinspection SpellCheckingInspection
    """TAFC: (T)ri(A)cetyl(F)usarinine C"""

    name = 'tafc'
    StateClass = TAFCState

    def initialize(self, state: State) -> State:
        tafc: TAFCState = state.tafc
        geometry: GeometryState = state.geometry
        voxel_volume = geometry.voxel_volume

        # config file values
        tafc.k_m_tf_tafc = self.config.getfloat('k_m_tf_tafc')

        # computed values
        tafc.tafc_qtty = self.config.getfloat('tafc_qtty') * 15  # TODO: unit_t
        tafc.tafc_up = self.config.getfloat('tafc_up') / voxel_volume / 15
        tafc.threshold = tafc.k_m_tf_tafc * voxel_volume / 1.0e6

        return state

    def advance(self, state: State, previous_time: float) -> State:
        """Advance the state by a single time step."""
        from nlisim.modulesv2.iron import IronState
        from nlisim.modulesv2.transferrin import TransferrinState
        from nlisim.modulesv2.afumigatus import AfumigatusCellData, AfumigatusCellState, AfumigatusCellStatus, \
            AfumigatusState, NetworkSpecies

        tafc: TAFCState = state.tafc
        transferrin: TransferrinState = state.transferrin
        iron: IronState = state.iron
        molecules: MoleculesState = state.molecules
        afumigatus: AfumigatusState = state.afumigatus
        grid: RectangularGrid = state.grid
        geometry: GeometryState = state.geometry
        voxel_volume = geometry.voxel_volume

        # interaction with transferrin
        # - calculate iron transfer from transferrin+[1,2]Fe to TAFC
        dfe2dt = self.michaelian_kinetics(substrate=transferrin.grid["TfFe2"],
                                          enzyme=tafc.grid["TAFC"],
                                          km=tafc.k_m_tf_tafc,
                                          h=self.time_step / 60,
                                          voxel_volume=voxel_volume)
        dfedt = self.michaelian_kinetics(substrate=transferrin.grid["TfFe"],
                                         enzyme=tafc.grid["TAFC"],
                                         km=tafc.k_m_tf_tafc,
                                         h=self.time_step / 60,
                                         voxel_volume=voxel_volume)

        # - enforce bounds from TAFC quantity
        with np.errstate(divide='ignore', invalid='ignore'):
            total_change = dfe2dt + dfedt
            rel = tafc.grid['TAFC'] / total_change
            rel[total_change == 0] = 0.0
            np.maximum(rel, 1.0, out=rel)
        dfe2dt = dfe2dt * rel
        dfedt = dfedt * rel

        # transferrin+2Fe loses an iron, becomes transferrin+Fe
        transferrin.grid['TfFe2'] -= dfe2dt
        transferrin.grid['TfFe'] += dfe2dt

        # transferrin+Fe loses an iron, becomes transferrin
        transferrin.grid['TfFe'] -= dfedt
        transferrin.grid['Tf'] += dfedt

        # iron from transferrin becomes bound to TAFC (TAFC->TAFCBI)
        tafc.grid['TAFC'] -= dfe2dt + dfedt
        tafc.grid['TAFCBI'] += dfe2dt + dfedt

        # interaction with iron, all available iron is bound to TAFC
        potential_reactive_quantity = np.minimum(iron.grid, tafc.grid['TAFC'])
        tafc.grid['TAFC'] -= potential_reactive_quantity
        tafc.grid['TAFCBI'] += potential_reactive_quantity
        iron.grid -= potential_reactive_quantity

        # interaction with fungus
        for afumigatus_cell_index in afumigatus.cells.alive():
            afumigatus_cell: AfumigatusCellData = afumigatus.cells[afumigatus_cell_index]

            if afumigatus_cell['state'] != AfumigatusCellState.FREE or \
                    afumigatus_cell['status'] == AfumigatusCellStatus.DYING:
                continue

            afumigatus_cell_voxel: Voxel = grid.get_voxel(afumigatus_cell['point'])
            afumigatus_bool_net: np.ndarray = afumigatus_cell['boolean_network']

            # uptake iron from TAFCBI
            if afumigatus_bool_net[NetworkSpecies.MirB] & afumigatus_bool_net[NetworkSpecies.EstB]:
                qtty = tafc.grid['TAFCBI'][tuple(afumigatus_cell_voxel)] * tafc.tafc_up
                # TODO: can't be bigger, unless tafc.tafc_up > 1. Am I missing something?
                # qtty = qtty if qtty < self.get("TAFCBI", x, y, z) else self.get("TAFCBI", x, y, z)
                tafc.grid['TAFCBI'][tuple(afumigatus_cell_voxel)] -= qtty
                afumigatus_cell['iron_pool'] += qtty

            # secrete TAFC
            if afumigatus_bool_net[NetworkSpecies.TAFC] and \
                    afumigatus_cell['status'] in {AfumigatusCellStatus.SWELLING_CONIDIA,
                                                  AfumigatusCellStatus.HYPHAE,
                                                  AfumigatusCellStatus.GERM_TUBE}:
                tafc.grid['TAFC'][tuple(afumigatus_cell_voxel)] += tafc.tafc_qtty

        # Degrade TAFC
        trnvr_rt = turnover_rate(x_mol=np.array(1.0, dtype=np.float64),
                                 x_system_mol=0.0,
                                 base_turnover_rate=molecules.turnover_rate,
                                 rel_cyt_bind_unit_t=molecules.rel_cyt_bind_unit_t)
        tafc.grid['TAFC'] *= trnvr_rt
        tafc.grid['TAFCBI'] *= trnvr_rt

        return state
