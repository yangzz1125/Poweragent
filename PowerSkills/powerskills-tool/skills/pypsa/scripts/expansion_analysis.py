#!/usr/bin/env python3
"""
Capacity expansion analysis for PyPSA networks.

These functions analyze capacity expansion optimization results and return
structured data for automated decision-making.

Typical usage:
    import pypsa
    from expansion_analysis import analyze_expansion, get_new_capacity
    
    network = pypsa.Network("network.nc")
    network.optimize()  # with extendable components
    
    results = analyze_expansion(network)
    print(f"Total investment: €{results['investment']['total']}")
"""

import pypsa
import pandas as pd
from typing import Dict, List, Optional


def get_new_capacity(network: pypsa.Network) -> Dict:
    """
    Calculate new capacity added through expansion.
    
    Args:
        network: PyPSA Network object (must have run optimize() with extendable components)
        
    Returns:
        dict: {
            'generators': {name: {'p_nom_old': float, 'p_nom_opt': float, 'p_nom_new': float, 'carrier': str}, ...},
            'storage_units': {name: {...}, ...},
            'stores': {name: {...}, ...},
            'lines': {name: {...}, ...},
            'links': {name: {...}, ...}
        }
    """
    result = {
        'generators': {},
        'storage_units': {},
        'stores': {},
        'lines': {},
        'links': {}
    }
    
    # Generators
    if len(network.generators) > 0 and 'p_nom_extendable' in network.generators.columns:
        extendable = network.generators[network.generators.p_nom_extendable]
        for gen in extendable.index:
            p_nom = float(network.generators.at[gen, 'p_nom'])
            p_nom_opt = float(network.generators.at[gen, 'p_nom_opt'])
            result['generators'][gen] = {
                'p_nom_old': p_nom,
                'p_nom_opt': p_nom_opt,
                'p_nom_new': p_nom_opt - p_nom,
                'carrier': network.generators.at[gen, 'carrier']
            }
    
    # Storage units
    if len(network.storage_units) > 0 and 'p_nom_extendable' in network.storage_units.columns:
        extendable = network.storage_units[network.storage_units.p_nom_extendable]
        for storage in extendable.index:
            p_nom = float(network.storage_units.at[storage, 'p_nom'])
            p_nom_opt = float(network.storage_units.at[storage, 'p_nom_opt'])
            result['storage_units'][storage] = {
                'p_nom_old': p_nom,
                'p_nom_opt': p_nom_opt,
                'p_nom_new': p_nom_opt - p_nom,
                'carrier': network.storage_units.at[storage, 'carrier']
            }
    
    # Stores
    if len(network.stores) > 0 and 'e_nom_extendable' in network.stores.columns:
        extendable = network.stores[network.stores.e_nom_extendable]
        for store in extendable.index:
            e_nom = float(network.stores.at[store, 'e_nom'])
            e_nom_opt = float(network.stores.at[store, 'e_nom_opt'])
            result['stores'][store] = {
                'e_nom_old': e_nom,
                'e_nom_opt': e_nom_opt,
                'e_nom_new': e_nom_opt - e_nom,
                'carrier': network.stores.at[store, 'carrier']
            }
    
    # Lines
    if len(network.lines) > 0 and 's_nom_extendable' in network.lines.columns:
        extendable = network.lines[network.lines.s_nom_extendable]
        for line in extendable.index:
            s_nom = float(network.lines.at[line, 's_nom'])
            s_nom_opt = float(network.lines.at[line, 's_nom_opt'])
            result['lines'][line] = {
                's_nom_old': s_nom,
                's_nom_opt': s_nom_opt,
                's_nom_new': s_nom_opt - s_nom
            }
    
    # Links
    if len(network.links) > 0 and 'p_nom_extendable' in network.links.columns:
        extendable = network.links[network.links.p_nom_extendable]
        for link in extendable.index:
            p_nom = float(network.links.at[link, 'p_nom'])
            p_nom_opt = float(network.links.at[link, 'p_nom_opt'])
            result['links'][link] = {
                'p_nom_old': p_nom,
                'p_nom_opt': p_nom_opt,
                'p_nom_new': p_nom_opt - p_nom
            }
    
    return result


def calculate_investment_costs(network: pypsa.Network) -> Dict:
    """
    Calculate total investment costs for capacity expansion.
    
    Args:
        network: PyPSA Network object (must have run optimize() with extendable components)
        
    Returns:
        dict: {
            'by_component_type': {'generators': float, 'storage_units': float, ...},
            'by_carrier': {carrier: float, ...},
            'total': float
        }
    """
    costs = {
        'by_component_type': {},
        'by_carrier': {},
        'total': 0.0
    }
    
    # Generators
    if len(network.generators) > 0 and 'p_nom_extendable' in network.generators.columns:
        extendable = network.generators[network.generators.p_nom_extendable]
        gen_costs = 0.0
        carrier_costs = {}
        
        for gen in extendable.index:
            p_nom_new = network.generators.at[gen, 'p_nom_opt'] - network.generators.at[gen, 'p_nom']
            if p_nom_new > 0:
                capital_cost = network.generators.at[gen, 'capital_cost']
                cost = p_nom_new * capital_cost
                gen_costs += cost
                
                carrier = network.generators.at[gen, 'carrier']
                carrier_costs[carrier] = carrier_costs.get(carrier, 0) + cost
        
        costs['by_component_type']['generators'] = gen_costs
        for carrier, cost in carrier_costs.items():
            costs['by_carrier'][carrier] = costs['by_carrier'].get(carrier, 0) + cost
        costs['total'] += gen_costs
    
    # Storage units
    if len(network.storage_units) > 0 and 'p_nom_extendable' in network.storage_units.columns:
        extendable = network.storage_units[network.storage_units.p_nom_extendable]
        storage_costs = 0.0
        
        for storage in extendable.index:
            p_nom_new = network.storage_units.at[storage, 'p_nom_opt'] - network.storage_units.at[storage, 'p_nom']
            if p_nom_new > 0:
                capital_cost = network.storage_units.at[storage, 'capital_cost']
                cost = p_nom_new * capital_cost
                storage_costs += cost
                
                carrier = network.storage_units.at[storage, 'carrier']
                costs['by_carrier'][carrier] = costs['by_carrier'].get(carrier, 0) + cost
        
        costs['by_component_type']['storage_units'] = storage_costs
        costs['total'] += storage_costs
    
    # Lines
    if len(network.lines) > 0 and 's_nom_extendable' in network.lines.columns:
        extendable = network.lines[network.lines.s_nom_extendable]
        line_costs = 0.0
        
        for line in extendable.index:
            s_nom_new = network.lines.at[line, 's_nom_opt'] - network.lines.at[line, 's_nom']
            if s_nom_new > 0:
                capital_cost = network.lines.at[line, 'capital_cost']
                cost = s_nom_new * capital_cost
                line_costs += cost
        
        costs['by_component_type']['lines'] = line_costs
        costs['by_carrier']['transmission'] = costs['by_carrier'].get('transmission', 0) + line_costs
        costs['total'] += line_costs
    
    # Links
    if len(network.links) > 0 and 'p_nom_extendable' in network.links.columns:
        extendable = network.links[network.links.p_nom_extendable]
        link_costs = 0.0
        
        for link in extendable.index:
            p_nom_new = network.links.at[link, 'p_nom_opt'] - network.links.at[link, 'p_nom']
            if p_nom_new > 0:
                capital_cost = network.links.at[link, 'capital_cost']
                cost = p_nom_new * capital_cost
                link_costs += cost
        
        costs['by_component_type']['links'] = link_costs
        costs['total'] += link_costs
    
    return costs


def get_capacity_by_carrier(network: pypsa.Network, use_optimal: bool = True) -> Dict:
    """
    Get total capacity by carrier after expansion.
    
    Args:
        network: PyPSA Network object
        use_optimal: If True, use p_nom_opt; if False, use p_nom
        
    Returns:
        dict: {carrier: float (MW), ...}
    """
    capacity = {}
    
    # Generators
    if len(network.generators) > 0:
        nom_col = 'p_nom_opt' if use_optimal else 'p_nom'
        for gen in network.generators.index:
            carrier = network.generators.at[gen, 'carrier']
            cap = float(network.generators.at[gen, nom_col])
            capacity[carrier] = capacity.get(carrier, 0) + cap
    
    # Storage units
    if len(network.storage_units) > 0:
        nom_col = 'p_nom_opt' if use_optimal else 'p_nom'
        for storage in network.storage_units.index:
            carrier = network.storage_units.at[storage, 'carrier']
            cap = float(network.storage_units.at[storage, nom_col])
            capacity[carrier] = capacity.get(carrier, 0) + cap
    
    return capacity


def analyze_expansion(network: pypsa.Network) -> Dict:
    """
    Complete capacity expansion analysis.
    
    This is the main function agents should use for expansion analysis.
    
    Args:
        network: PyPSA Network object (must have run optimize() with extendable components)
        
    Returns:
        dict: {
            'new_capacity': {...},
            'investment': {...},
            'capacity_before': {...},
            'capacity_after': {...}
        }
    """
    return {
        'new_capacity': get_new_capacity(network),
        'investment': calculate_investment_costs(network),
        'capacity_before': get_capacity_by_carrier(network, use_optimal=False),
        'capacity_after': get_capacity_by_carrier(network, use_optimal=True)
    }


def print_expansion_report(analysis_results: Dict):
    """
    Print formatted report from analyze_expansion results.
    
    Args:
        analysis_results: Dict returned by analyze_expansion()
    """
    new_cap = analysis_results['new_capacity']
    investment = analysis_results['investment']
    cap_before = analysis_results['capacity_before']
    cap_after = analysis_results['capacity_after']
    
    print("="*60)
    print("PyPSA Capacity Expansion Results")
    print("="*60)
    
    print(f"\nTotal Investment: €{investment['total']:,.0f}")
    
    if investment['by_component_type']:
        print("\nInvestment by Component Type:")
        for comp_type, cost in investment['by_component_type'].items():
            if cost > 0:
                print(f"  {comp_type:20s}: €{cost:>15,.0f}")
    
    if investment['by_carrier']:
        print("\nInvestment by Technology:")
        for carrier, cost in sorted(investment['by_carrier'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {carrier:20s}: €{cost:>15,.0f}")
    
    # New generator capacity
    if new_cap['generators']:
        print("\nNew Generator Capacity:")
        by_carrier = {}
        for gen, data in new_cap['generators'].items():
            if data['p_nom_new'] > 0:
                carrier = data['carrier']
                by_carrier[carrier] = by_carrier.get(carrier, 0) + data['p_nom_new']
        
        for carrier, cap in sorted(by_carrier.items(), key=lambda x: x[1], reverse=True):
            print(f"  {carrier:20s}: {cap:>10.1f} MW")
    
    # New transmission capacity
    if new_cap['lines']:
        new_lines = [name for name, data in new_cap['lines'].items() if data['s_nom_new'] > 0]
        if new_lines:
            print(f"\nNew/Expanded Transmission Lines: {len(new_lines)}")
            for line in new_lines[:5]:
                data = new_cap['lines'][line]
                print(f"  {line}: +{data['s_nom_new']:.1f} MVA")
    
    # Capacity comparison
    print("\nCapacity Comparison (Before → After):")
    all_carriers = set(cap_before.keys()) | set(cap_after.keys())
    for carrier in sorted(all_carriers):
        before = cap_before.get(carrier, 0)
        after = cap_after.get(carrier, 0)
        change = after - before
        pct_change = (change / before * 100) if before > 0 else float('inf')
        
        if change != 0:
            print(f"  {carrier:20s}: {before:>8.1f} → {after:>8.1f} MW ({change:+.1f} MW, {pct_change:+.0f}%)")
    
    print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python expansion_analysis.py <network_file.nc>")
        print("\nExample:")
        print("  python expansion_analysis.py my_network.nc")
        sys.exit(1)
    
    network_file = sys.argv[1]
    
    print(f"Loading network from {network_file}...")
    network = pypsa.Network(network_file)
    
    print("Running capacity expansion optimization...")
    network.optimize()
    
    # Run analysis
    results = analyze_expansion(network)
    print_expansion_report(results)
