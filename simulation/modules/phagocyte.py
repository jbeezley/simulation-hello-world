from enum import IntEnum
import math
import random

import attr
import numpy as np

from simulation.cell import CellData, CellList
from simulation.coordinates import Point, Voxel
from simulation.grid import RectangularGrid
from simulation.modules.geometry import TissueTypes

class PhagocyteCellData(CellData):
    RECRUIT_RATE = 0.0
    LEAVE_RATE = 0.0

    class Status(IntEnum):
        RESTING = 0
        ACTIVE = 1
        INTERACTING = 2
        SECRETING = 3
        SYNERGIC = 4
        APOPTOTIC = 5
        NECROTIC = 6
        DEAD = 7
        LEFT = 8

    PHAGOCYTE_FIELDS = [
        ('status', 'u1'),
        ('iron_pool', 'f8'),
        ('iteration', 'i4'),
    ]

    dtype = np.dtype(CellData.FIELDS + PHAGOCYTE_FIELDS, align=True)  # type: ignore

    @classmethod
    def create_cell_tuple(
        cls, *, iron_pool: float = 0, status: Status = Status.RESTING, **kwargs,
    ) -> np.record:

        iteration = 0

        return CellData.create_cell_tuple(**kwargs) + (status, iron_pool, iteration,)


@attr.s(kw_only=True, frozen=True, repr=False)
class PhagocyteCellList(CellList):
    CellDataClass = PhagocyteCellData

    def is_moveable(self, grid: RectangularGrid):
        cells = self.cell_data
        return self.alive(
            (cells['status'] == PhagocyteCellData.Status.RESTING)
            & cells.point_mask(cells['point'], grid)
        )

    def recruit(self, rate, tissue, grid: RectangularGrid):
        # TODO - add recruitment
        # indices = np.argwhere(molecule_to_recruit >= threshold_value)
        # then for each index create a cell with prob 'rec_rate'
        return


    def remove(self, rate, tissue, grid: RectangularGrid):
        # TODO - add leaving
        # indices = np.argwhere(molecule_to_leave <= threshold_value)
        # then for each index kill a cell with prob 'leave_rate'
        return


    # move
    def chemotaxis(
        self,
        molecule,
        drift_lambda,
        drift_bias,
        tissue,
        grid: RectangularGrid,
    ):
        # 'molecule' = state.'molecule'.concentration
        # prob = 0-1 random number to determine which voxel is chosen to move

        # 1. Get cells that are alive
        for index in self.alive():
            prob = random.random()
            
            # 2. Get voxel for each cell to get molecule in that voxel
            cell = self[index]
            vox = grid.get_voxel(cell['point'])

            # 3. Set prob for neighboring voxels
            p = []
            vox_list = []
            p_tot = 0.0
            i = -1

            # calculate individual probability
            for x in [0, 1, -1]:
                for y in [0, 1, -1]:
                    for z in [0, 1, -1]:
                        p.append(0.0)
                        vox_list.append([x, y, z])
                        i += 1
                        zk = vox.z + z
                        yj = vox.y + y
                        xi = vox.x + x
                        if grid.is_valid_voxel(Voxel(x=xi, y=yj, z=zk)):
                            if tissue[zk, yj, xi] in [
                                TissueTypes.SURFACTANT.value,
                                TissueTypes.BLOOD.value,
                                TissueTypes.EPITHELIUM.value,
                                TissueTypes.PORE.value,
                            ]:
                                p[i] = logistic(
                                    molecule[zk, yj, xi], drift_lambda, drift_bias
                                )
                                p_tot += p[i]

            # scale to sum of probabilities
            if p_tot:
                for i in range(len(p)):
                    p[i] = p[i] / p_tot

            # chose vox from neighbors
            cum_p = 0.0
            for i in range(len(p)):
                cum_p += p[i]
                if prob <= cum_p:
                    cell['point'] = Point(
                        x=grid.x[vox.x + vox_list[i][0]],  # TODO plus random,
                        y=grid.y[vox.y + vox_list[i][1]],  # TODO plus random,
                        z=grid.z[vox.z + vox_list[i][2]],  # TODO plus random,
                    )
                    self.update_voxel_index([index])
                    break


def logistic(x, l, b):
    return 1 - b * math.exp(-((x / l) ** 2))