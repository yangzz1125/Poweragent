#!/usr/bin/env python3
"""
Network inspection and statistics for PyPSA networks.

These functions are designed for agent use - they return structured data
suitable for automated decision-making.

Typical usage:
    import pypsa
    from network_analysis import summarize_network, get_capacity_by_carrier, analyze_network
    
    network = pypsa.Network("network.nc")
    summary = summarize_network(network)
    capacity = get_capacity_by_carrier(network)
"""

import pypsa
import pandas as pd
from typing import Dict, List, Optional


def summarize_network(network: pypsa.Network) -> Dict:
    """
    Get network component counts and basic statistics.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: {
            'name': str,
            'snapshots': {
                'count': int,
                'start': str,
                'end': str,
                'freq': str
            },
            'components': {
                'buses': int,
                'generators': int,
                'loads': int,
                'lines': int,
                'links': int,
                'storage_units': int,
                'stores': int,
                'transformers': int
            }
        }
    """
    summary = {
        'name': network.name,
        'snapshots': {
            'count': len(network.snapshots),
            'start': str(network.snapshots[0]) if len(network.snapshots) > 0 else None,
            'end': str(network.snapshots[-1]) if len(network.snapshots) > 0 else None,
            'freq': str(network.snapshots.freq) if hasattr(network.snapshots, 'freq') else None
        },
        'components': {
            'buses': len(network.buses),
            'generators': len(network.generators),
            'loads': len(network.loads),
            'lines': len(network.lines),
            'links': len(network.links),
            'storage_units': len(network.storage_units),
            'stores': len(network.stores),
            'transformers': len(network.transformers)
        }
    }
    
    return summary


def get_capacity_by_carrier(network: pypsa.Network) -> Dict:
    """
    Get installed capacity grouped by energy carrier/technology.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: {
            'generators': {'carrier_name': float (MW), ...},
            'storage_units': {'carrier_name': float (MW), ...},
            'stores': {'carrier_name': float (MWh), ...}
        }
    """
    result = {}
    
    # Generator capacity by carrier
    if len(network.generators) > 0:
        gen_capacity = network.generators.groupby('carrier')['p_nom'].sum()
        result['generators'] = gen_capacity.to_dict()
    else:
        result['generators'] = {}
    
    # Storage unit capacity by carrier
    if len(network.storage_units) > 0:
        storage_capacity = network.storage_units.groupby('carrier')['p_nom'].sum()
        result['storage_units'] = storage_capacity.to_dict()
    else:
        result['storage_units'] = {}
    
    # Store capacity by carrier
    if len(network.stores) > 0:
        store_capacity = network.stores.groupby('carrier')['e_nom'].sum()
        result['stores'] = store_capacity.to_dict()
    else:
        result['stores'] = {}
    
    return result


def get_total_load(network: pypsa.Network) -> Dict:
    """
    Calculate total load across all snapshots.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: {
            'total_mwh': float,
            'average_mw': float,
            'peak_mw': float,
            'by_bus': {bus_name: float (MWh), ...}
        }
    """
    if len(network.loads) == 0:
        return {
            'total_mwh': 0.0,
            'average_mw': 0.0,
            'peak_mw': 0.0,
            'by_bus': {}
        }
    
    # Get load time series
    load_t = network.loads_t.p_set
    
    # Calculate statistics
    total_mwh = float(load_t.sum().sum())
    average_mw = float(load_t.sum(axis=1).mean())
    peak_mw = float(load_t.sum(axis=1).max())
    
    # Load by bus
    load_by_bus = {}
    for load_name in network.loads.index:
        bus = network.loads.at[load_name, 'bus']
        load_mwh = float(load_t[load_name].sum())
        if bus in load_by_bus:
            load_by_bus[bus] += load_mwh
        else:
            load_by_bus[bus] = load_mwh
    
    return {
        'total_mwh': total_mwh,
        'average_mw': average_mw,
        'peak_mw': peak_mw,
        'by_bus': load_by_bus
    }


def check_extendable_components(network: pypsa.Network) -> Dict:
    """
    Identify which components are set as extendable for capacity expansion.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: {
            'generators': list of extendable generator names,
            'storage_units': list of extendable storage unit names,
            'stores': list of extendable store names,
            'lines': list of extendable line names,
            'links': list of extendable link names
        }
    """
    result = {}
    
    # Generators
    if len(network.generators) > 0 and 'p_nom_extendable' in network.generators.columns:
        extendable = network.generators[network.generators.p_nom_extendable].index.tolist()
        result['generators'] = extendable
    else:
        result['generators'] = []
    
    # Storage units
    if len(network.storage_units) > 0 and 'p_nom_extendable' in network.storage_units.columns:
        extendable = network.storage_units[network.storage_units.p_nom_extendable].index.tolist()
        result['storage_units'] = extendable
    else:
        result['storage_units'] = []
    
    # Stores
    if len(network.stores) > 0 and 'e_nom_extendable' in network.stores.columns:
        extendable = network.stores[network.stores.e_nom_extendable].index.tolist()
        result['stores'] = extendable
    else:
        result['stores'] = []
    
    # Lines
    if len(network.lines) > 0 and 's_nom_extendable' in network.lines.columns:
        extendable = network.lines[network.lines.s_nom_extendable].index.tolist()
        result['lines'] = extendable
    else:
        result['lines'] = []
    
    # Links
    if len(network.links) > 0 and 'p_nom_extendable' in network.links.columns:
        extendable = network.links[network.links.p_nom_extendable].index.tolist()
        result['links'] = extendable
    else:
        result['links'] = []
    
    return result


def analyze_network(network: pypsa.Network) -> Dict:
    """
    Complete network analysis combining all inspection functions.
    
    This is the main function agents should use for network analysis.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: Combined results from all analysis functions
    """
    return {
        'summary': summarize_network(network),
        'capacity': get_capacity_by_carrier(network),
        'load': get_total_load(network),
        'extendable': check_extendable_components(network)
    }


def print_network_report(analysis_results: Dict):
    """
    Print formatted report from analyze_network results.
    
    Args:
        analysis_results: Dict returned by analyze_network()
    """
    summary = analysis_results['summary']
    capacity = analysis_results['capacity']
    load = analysis_results['load']
    extendable = analysis_results['extendable']
    
    print("="*60)
    print(f"PyPSA Network Analysis: {summary['name']}")
    print("="*60)
    
    print("\nTime Period:")
    print(f"  Snapshots: {summary['snapshots']['count']}")
    print(f"  From: {summary['snapshots']['start']}")
    print(f"  To:   {summary['snapshots']['end']}")
    
    print("\nNetwork Components:")
    for comp, count in summary['components'].items():
        if count > 0:
            print(f"  {comp:20s}: {count}")
    
    print("\nInstalled Capacity:")
    if capacity['generators']:
        print("  Generators:")
        for carrier, cap in capacity['generators'].items():
            print(f"    {carrier:18s}: {cap:>10.1f} MW")
    
    if capacity['storage_units']:
        print("  Storage Units:")
        for carrier, cap in capacity['storage_units'].items():
            print(f"    {carrier:18s}: {cap:>10.1f} MW")
    
    if capacity['stores']:
        print("  Stores:")
        for carrier, cap in capacity['stores'].items():
            print(f"    {carrier:18s}: {cap:>10.1f} MWh")
    
    print("\nTotal Load:")
    print(f"  Total:   {load['total_mwh']:.1f} MWh")
    print(f"  Average: {load['average_mw']:.1f} MW")
    print(f"  Peak:    {load['peak_mw']:.1f} MW")
    
    # Check for extendable components
    total_extendable = sum(len(v) for v in extendable.values())
    if total_extendable > 0:
        print("\nExtendable Components:")
        for comp_type, items in extendable.items():
            if items:
                print(f"  {comp_type}: {len(items)}")
    
    print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python network_analysis.py <network_file.nc>")
        print("\nExample:")
        print("  python network_analysis.py my_network.nc")
        sys.exit(1)
    
    network_file = sys.argv[1]
    
    print(f"Loading network from {network_file}...")
    
    try:
        network = pypsa.Network(network_file)
    except Exception as e:
        print(f"ERROR: Failed to load network: {e}")
        sys.exit(1)
    
    # Run analysis
    results = analyze_network(network)
    print_network_report(results)
