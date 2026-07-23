"""Memory-bounded resource-only reconstruction of the paper-era DVG pool.

This module cannot prepare states or evaluate energies. It reproduces only the
operator ordering and native circuit metadata needed by the paper-era counters.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
from typing import Any


class ResourcePoolError(RuntimeError):
    """Raised when the resource-only pool cannot reproduce upstream semantics."""


def _excitation_key(source: list[int], target: list[int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    forward = (tuple(source), tuple(target))
    reverse = (tuple(target), tuple(source))
    return min(forward, reverse)


def _exchange_pairs(p: int, q: int, r: int, s: int) -> list[tuple[list[list[int]], list[list[int]]]]:
    pairs: list[tuple[list[list[int]], list[list[int]]]] = []
    if (p + r) % 2 == 0:
        pairs.append(([[r, s], [p, s]], [[p, q], [q, r]]))
    if (p + q) % 2 == 0:
        pairs.append(([[q, s], [p, s]], [[p, r], [q, r]]))
    if (p + s) % 2 == 0:
        pairs.append(([[r, s], [q, s]], [[p, q], [p, r]]))
    return pairs


@dataclass
class ResourceOnlyOperator:
    source_orbs: Any
    target_orbs: Any
    qubits: set[int]
    ceo_type: str | None = None
    parents: list[int] | None = None
    component_parents: tuple[int, int] | None = None


class ResourceOnlyDVGPool:
    """Lazy DVG pool for circuit/resource reconstruction only."""

    name = "DVG_CEO"

    def __init__(self, n: int) -> None:
        if n <= 0:
            raise ResourcePoolError("qubit count must be positive")
        self.n = int(n)
        self.operators: list[ResourceOnlyOperator] = []
        self._operator_cache: dict[int, Any] = {}
        self._ops_on_support: dict[tuple[int, ...], list[int]] = {}
        excitation_positions: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = {}

        for p in range(n):
            for q in range(p + 1, n):
                if (p + q) % 2 == 0:
                    key = _excitation_key([q], [p])
                    excitation_positions[key] = len(self.operators)
                    self.operators.append(ResourceOnlyOperator([q], [p], {p, q}))
                    self._ops_on_support[(p, q)] = [len(self.operators) - 1]
        first_double = len(self.operators)

        valid_supports: list[tuple[int, int, int, int]] = []
        for p, q, r, s in itertools.combinations(range(n), 4):
            if (p + q + r + s) % 2 != 0:
                continue
            support = (p, q, r, s)
            valid_supports.append(support)
            positions: list[int] = []
            for sources, targets in _exchange_pairs(p, q, r, s):
                for source, target in zip(sources, targets):
                    key = _excitation_key(source, target)
                    if key not in excitation_positions:
                        excitation_positions[key] = len(self.operators)
                        self.operators.append(
                            ResourceOnlyOperator(list(source), list(target), set(support))
                        )
                    positions.append(excitation_positions[key])
            ordered_unique = list(dict.fromkeys(positions))
            self._ops_on_support[support] = ordered_unique

        parent_size = len(self.operators)
        self.parent_range = range(first_double, parent_size)
        for support in valid_supports:
            parents = self._ops_on_support[support]
            p, q, r, s = support
            for sources, targets in _exchange_pairs(p, q, r, s):
                component_positions = tuple(
                    excitation_positions[_excitation_key(source, target)]
                    for source, target in zip(sources, targets)
                )
                if len(component_positions) != 2:
                    raise ResourcePoolError("OVP must have exactly two component QEs")
                for ceo_type in ("sum", "diff"):
                    self.operators.append(
                        ResourceOnlyOperator(
                            [list(value) for value in sources],
                            [list(value) for value in targets],
                            set(support),
                            ceo_type,
                            list(parents),
                            component_positions,
                        )
                    )

    @property
    def size(self) -> int:
        return len(self.operators)

    def get_qubits(self, index: int) -> set[int]:
        return self.operators[index].qubits

    def get_q_op(self, index: int) -> Any:
        if index in self._operator_cache:
            return self._operator_cache[index]
        try:
            from openfermion import FermionOperator, QubitOperator, hermitian_conjugated, normal_ordered
            from adaptvqe.chemistry import normalize_op
            from adaptvqe.utils import remove_z_string
        except ImportError as error:
            raise ResourcePoolError("paper-era operator dependencies are unavailable") from error
        operator = self.operators[index]
        if operator.component_parents is not None:
            left = self.get_q_op(operator.component_parents[0])
            right = self.get_q_op(operator.component_parents[1])
            q_operator = left + right if operator.ceo_type == "sum" else left - right
            q_operator = normalize_op(q_operator)
        else:
            source = operator.source_orbs
            target = operator.target_orbs
            term = tuple((orbital, 1) for orbital in target) + tuple(
                (orbital, 0) for orbital in source
            )
            fermion = FermionOperator(term)
            fermion -= hermitian_conjugated(fermion)
            fermion = normal_ordered(fermion)
            q_operator = normalize_op(remove_z_string(fermion))
        self._operator_cache[index] = q_operator
        return q_operator

    def get_circuit(self, indices: list[int], coefficients: list[float]) -> Any:
        if len(indices) != len(coefficients):
            raise ResourcePoolError("circuit indices and coefficients differ in length")
        try:
            from openfermion import QubitOperator
            from qiskit import QuantumCircuit
            from adaptvqe.circuits import mvp_ceo_circuit, ovp_ceo_circuit, qe_circuit
        except ImportError as error:
            raise ResourcePoolError("paper-era circuit dependencies are unavailable") from error
        circuit = QuantumCircuit(self.n)
        parent_range = set(self.parent_range)
        accumulated_indices: list[int] = []
        accumulated_coefficients: list[float] = []
        for position, (index, coefficient) in enumerate(zip(indices, coefficients)):
            operator = self.operators[index]
            if index not in parent_range:
                block = ovp_ceo_circuit(
                    operator.source_orbs,
                    operator.target_orbs,
                    self.n,
                    coefficient,
                    operator.ceo_type,
                    big_endian=True,
                )
            else:
                accumulated_indices.append(index)
                accumulated_coefficients.append(coefficient)
                next_is_same_parent_block = (
                    position + 1 < len(indices)
                    and indices[position + 1] in parent_range
                    and self.get_qubits(indices[position + 1]) == self.get_qubits(index)
                )
                if next_is_same_parent_block:
                    block = None
                elif len(accumulated_indices) == 1:
                    block = qe_circuit(
                        operator.source_orbs,
                        operator.target_orbs,
                        coefficient,
                        self.n,
                        big_endian=True,
                    )
                    accumulated_indices = []
                    accumulated_coefficients = []
                else:
                    q_operator = QubitOperator()
                    for pool_index, value in zip(accumulated_indices, accumulated_coefficients):
                        q_operator += value * self.get_q_op(pool_index)
                    block = mvp_ceo_circuit(q_operator, self.n, big_endian=True)
                    accumulated_indices = []
                    accumulated_coefficients = []
            if block is not None:
                circuit = circuit.compose(block)
                circuit.barrier()
        return circuit
