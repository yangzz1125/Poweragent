#!/usr/bin/env python3
"""
Optimization results analysis for PyPSA networks.

These functions analyze optimization results and return structured data
for automated decision-making.

Typical usage:
    import pypsa
    from optimization_analysis import analyze_optimization, get_generation_mix
    
    network = pypsa.Network("network.nc")
    network.optimize()
    
    results = analyze_optimization(network)
    if results['converged']:
        print(f"Total cost: {results['objective']}")
```

import pypsa
import pandas as pd
from typing import Dict, List, Optional


def check_optimization_status(network: pypsa.Network) -> Dict:
    """
    Check if optimization has been run and was successful.
    
    Args:
        network: PyPSA Network object
        
    Returns:
        dict: {
            'optimized': bool,
            'converged': bool,
            'status': str,
            'objective': float (if converged),
            'solver': str (if available)
        }
    """
    if not hasattr(network, 'objective') or network.objective is None:
        return {
            'optimized': False,
            'converged': False,
            'status': 'not_run'
        }
    
    result = {
        'optimized': True,
        'objective': float(network.objective)
    }
    
    if hasattr(network, 'status'):
        result['converged'] = network.status.get('status', '') == 'ok'
        result['status'] = network.status.get('status', 'unknown')
        result['solver'] = network.status.get('solver', 'unknown')
    else:
        result['converged'] = True  # assume success if no status attribute
        result['status'] = 'ok'
    
    return result


def get_generation_mix(network: pypsa.Network) -> Dict:
    """
    Calculate generation mix from optimization results.
    
    Args:
        network: PyPSA Network object (must have run optimize())
        
    Returns:
        dict: {
            'by_carrier': {carrier: float (MWh), ...},
            'by_generator': {gen_name: float (MWh), ...},
            'total_mwh': float
        }
    """
    if network.generators_t.p.empty:
        return {
            'by_carrier': {},
            'by_generator': {},
            'total_mwh': 0.0
        }
    
    # Total generation by each generator
    gen_total = network.generators_t.p.sum()
    by_generator = gen_total.to_dict()
    total_mwh = float(gen_total.sum())
    
    # Generation by carrier
    by_carrier = {}
    for gen_name, mwh in by_generator.items():
        carrier = network.generators.at[gen_name, 'carrier']
        if carrier in by_carrier:
            by_carrier[carrier] += mwh
        else:
            by_carrier[carrier] = mwh
    
    return {
        'by_carrier': by_carrier,
        'by_generator': by_generator,
        'total_mwh': total_mwh
    }


def get_curtailment(network: pypsa.Network) -> Dict:
    """
    Calculate renewable energy curtailment.
    
    Args:
        network: PyPSA Network object (must have run optimize())
        
    Returns:
        dict: {
            'by_generator': {gen_name: {'available': float, 'used': float, 'curtailed': float, 'curtailment_rate': float}, ...},
            'total_curtailed_mwh': float,
            'total_curtailment_rate': float
        }
    """
    if network.generators_t.p.empty or network.generators_t.p_max_pu.empty:
        return {
            'by_generator': {},
            'total_curtailed_mwh': 0.0,
            'total_curtailment_rate': 0.0
        }
    
    curtailment = {}
    total_available = 0.0
    total_used = 0.0
    
    for gen in network.generators.index:
        if gen not in network.generators_t.p_max_pu.columns:
            continue
        
        p_nom = network.generators.at[gen, 'p_nom']
        
        # Available generation
        available = (network.generators_t.p_max_pu[gen] * p_nom).sum()
        
        # Actual generation
        used = network.generators_t.p[gen].sum()
        
        # Curtailed
        curtailed = available - used
        
        if available > 0:
            curtailment_rate = curtailed / available
            curtailment[gen] = {
                'available': float(available),
                'used': float(used),
                'curtailed': float(curtailed),
                'curtailment_rate': float(curtailment_rate)
            }
            
            total_available += available
            total_used += used
    
    total_curtailed = total_available - total_used
    total_rate = total_curtailed / total_available if total_available > 0 else 0.0
    
    return {
        'by_generator': curtailment,
        'total_curtailed_mwh': float(total_curtailed),
        'total_curtailment_rate': float(total_rate)
    }


def get_storage_operation(network: pypsa.Network) -> Dict:
    """
    Analyze storage operation from optimization results.
    
    Args:
        network: PyPSA Network object (must have run optimize())
        
    Returns:
        dict: {
            'storage_units': {name: {'charge': float, 'discharge': float, 'cycles': float}, ...},
            'stores': {name: {'inflow': float, 'outflow': float}, ...}
        }
    """
    result = {
        'storage_units': {},
        'stores': {}
    }
    
    # Storage units
    if not network.storage_units_t.p.empty:
        for storage in network.storage_units.index:
            p = network.storage_units_t.p[storage]
            
            charge = float(p[p > 0].sum())
            discharge = float(-p[p < 0].sum())
            
            # Estimate cycles (energy throughput / energy capacity)
            max_hours = network.storage_units.at[storage, 'max_hours']
            p_nom = network.storage_units.at[storage, 'p_nom']
            energy_capacity = max_hours * p_nom
            cycles = discharge / energy_capacity if energy_capacity > 0 else 0.0
            
            result['storage_units'][storage] = {
                'charge_mwh': charge,
                'discharge_mwh': discharge,
                'cycles': cycles
            }
    
    # Stores (via connected links)
    # Note: Stores are charged/discharged through links, so we'd need to trace links
    # For simplicity, just report state of charge if available
    if not network.stores_t.e.empty:
        for store in network.stores.index:
            e = network.stores_t.e[store]
            result['stores'][store] = {
                'min_energy_mwh': float(e.min()),
                'max_energy_mwh': float(e.max()),
                'avg_energy_mwh': float(e.mean())
            }
    
    return result


def get_line_loading(network: pypsa.Network) -> Dict:
    """
    Calculate line loading statistics.
    
    Args:
        network: PyPSA Network object (must have run optimize())
        
    Returns:
        dict: {
            'lines': {line_name: {'max_loading': float, 'avg_loading': float, 'congested_hours': int}, ...},
            'most_congested': list of (line_name, max_loading) tuples
        }
    """
    if network.lines_t.p0.empty:
        return {
            'lines': {},
            'most_congested': []
        }
    
    line_stats = {}
    
    for line in network.lines.index:
        if line not in network.lines_t.p0.columns:
            continue
        
        p = network.lines_t.p0[line].abs()
        s_nom = network.lines.at[line, 's_nom']
        
        if s_nom > 0:
            loading = (p / s_nom * 100)
            
            line_stats[line] = {
                'max_loading': float(loading.max()),
                'avg_loading': float(loading.mean()),
                'congested_hours': int((loading >= 99).sum())
            }
    
    # Most congested lines
    most_congested = sorted(
        [(name, stats['max_loading']) for name, stats in line_stats.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    return {
        'lines': line_stats,
        'most_congested': most_congested
    }


def analyze_optimization(network: pypsa.Network) -> Dict:
    """
    Complete optimization results analysis.
    
    This is the main function agents should use for optimization analysis.
    
    Args:
        network: PyPSA Network object (must have run optimize())
        
    Returns:
        dict: Combined results from all optimization analysis functions
    """
    status = check_optimization_status(network)
    
    if not status['optimized']:
        return {
            'error': 'Network has not been optimized',
            'optimized': False
        }
    
    if not status['converged']:
        return {
            'error': f"Optimization failed: {status.get('status', 'unknown')}",
            'optimized': True,
            'converged': False
        }
    
    return {
        'status': status,
        'generation': get_generation_mix(network),
        'curtailment': get_curtailment(network),
        'storage': get_storage_operation(network),
        'transmission': get_line_loading(network)
    }


def print_optimization_report(analysis_results: Dict):
    """
    Print formatted report from analyze_optimization results.
    
    Args:
        analysis_results: Dict returned by analyze_optimization()
    """
    if 'error' in analysis_results:
        print(f"ERROR: {analysis_results['error']}")
        return
    
    status = analysis_results['status']
    generation = analysis_results['generation']
    curtailment = analysis_results['curtailment']
    storage = analysis_results['storage']
    transmission = analysis_results['transmission']
    
    print("="*60)
    print("PyPSA Optimization Results")
    print("="*60)
    
    print(f"\nOptimization Status: {status['status'].upper()}")
    print(f"Total Cost: €{status['objective']:,.0f}")
    if 'solver' in status:
        print(f"Solver: {status['solver']}")
    
    print("\nGeneration Mix:")
    for carrier, mwh in sorted(generation['by_carrier'].items(), key=lambda x: x[1], reverse=True):
        pct = mwh / generation['total_mwh'] * 100 if generation['total_mwh'] > 0 else 0
        print(f"  {carrier:20s}: {mwh:>12.1f} MWh ({pct:5.1f}%)")
    print(f"  {'TOTAL':20s}: {generation['total_mwh']:>12.1f} MWh")
    
    if curtailment['by_generator']:
        print("\nRenewable Curtailment:")
        print(f"  Total curtailed: {curtailment['total_curtailed_mwh']:.1f} MWh ({curtailment['total_curtailment_rate']*100:.1f}%)")
        
        # Show generators with significant curtailment
        significant = {k: v for k, v in curtailment['by_generator'].items() if v['curtailment_rate'] > 0.01}
        if significant:
            print("  By generator (>1% curtailment):")
            for gen, stats in significant.items():
                print(f"    {gen}: {stats['curtailed']:.1f} MWh ({stats['curtailment_rate']*100:.1f}%)")
    
    if storage['storage_units']:
        print("\nStorage Operation:")
        for storage, stats in storage['storage_units'].items():
            print(f"  {storage}:")
            print(f"    Charge:    {stats['charge_mwh']:.1f} MWh")
            print(f"    Discharge: {stats['discharge_mwh']:.1f} MWh")
            print(f"    Cycles:    {stats['cycles']:.1f}")
    
    if transmission['most_congested']:
        print("\nMost Congested Lines:")
        for line, loading in transmission['most_congested'][:5]:
            congested_hrs = transmission['lines'][line]['congested_hours']
            print(f"  {line}: {loading:.1f}% max loading ({congested_hrs} congested hours)")
    
    print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python optimization_analysis.py <network_file.nc>")
        print("\nExample:")
        print("  python optimization_analysis.py my_network.nc")
        sys.exit(1)
    
    network_file = sys.argv[1]
    
    print(f"Loading network from {network_file}...")
    network = pypsa.Network(network_file)
    
    print("Running optimization...")
    network.optimize()
    
    # Run analysis
    results = analyze_optimization(network)
    print_optimization_report(results)
