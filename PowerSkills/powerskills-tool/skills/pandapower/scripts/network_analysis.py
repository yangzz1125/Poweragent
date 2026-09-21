#!/usr/bin/env python3
"""
Core analysis functions for pandapower networks.

These functions are designed for agent use - they return structured data
and can be composed together for custom analysis workflows.

Typical usage:
    import pandapower as pp
    from network_analysis import check_violations, calculate_losses, summarize_network
    
    net = pp.from_json("network.json")
    pp.runpp(net)
    
    violations = check_violations(net)
    losses = calculate_losses(net)
    summary = summarize_network(net)
"""

import pandapower as pp
import pandas as pd
from typing import Dict, List, Tuple, Optional


def check_violations(
    net: pp.pandapowerNet,
    v_min: float = 0.95,
    v_max: float = 1.05,
    loading_limit: float = 100.0
) -> Dict:
    """
    Check for voltage and loading violations in the network.
    
    Args:
        net: pandapower network (must have run pp.runpp first)
        v_min: Minimum voltage limit (p.u.)
        v_max: Maximum voltage limit (p.u.)
        loading_limit: Maximum loading limit (%)
        
    Returns:
        dict: {
            'has_violations': bool,
            'voltage': {
                'undervoltage_buses': list of bus indices,
                'overvoltage_buses': list of bus indices,
                'min_voltage': float,
                'max_voltage': float
            },
            'loading': {
                'overloaded_lines': list of line indices,
                'overloaded_trafos': list of trafo indices,
                'max_line_loading': float,
                'max_trafo_loading': float
            }
        }
    """
    if not net.converged:
        return {
            'has_violations': True,
            'converged': False,
            'error': 'Power flow did not converge'
        }
    
    # Voltage violations
    undervoltage_buses = net.res_bus[net.res_bus.vm_pu < v_min].index.tolist()
    overvoltage_buses = net.res_bus[net.res_bus.vm_pu > v_max].index.tolist()
    
    # Loading violations
    overloaded_lines = net.res_line[net.res_line.loading_percent > loading_limit].index.tolist()
    overloaded_trafos = []
    if len(net.trafo) > 0:
        overloaded_trafos = net.res_trafo[net.res_trafo.loading_percent > loading_limit].index.tolist()
    
    has_violations = bool(
        undervoltage_buses or overvoltage_buses or 
        overloaded_lines or overloaded_trafos
    )
    
    return {
        'has_violations': has_violations,
        'converged': True,
        'voltage': {
            'undervoltage_buses': undervoltage_buses,
            'overvoltage_buses': overvoltage_buses,
            'min_voltage': float(net.res_bus.vm_pu.min()),
            'max_voltage': float(net.res_bus.vm_pu.max())
        },
        'loading': {
            'overloaded_lines': overloaded_lines,
            'overloaded_trafos': overloaded_trafos,
            'max_line_loading': float(net.res_line.loading_percent.max()) if len(net.res_line) > 0 else 0.0,
            'max_trafo_loading': float(net.res_trafo.loading_percent.max()) if len(net.trafo) > 0 else 0.0
        }
    }


def calculate_losses(net: pp.pandapowerNet) -> Dict:
    """
    Calculate system losses.
    
    Args:
        net: pandapower network (must have run pp.runpp first)
        
    Returns:
        dict: {
            'total_losses_mw': float,
            'total_losses_mvar': float,
            'line_losses_mw': float,
            'line_losses_mvar': float,
            'trafo_losses_mw': float,
            'trafo_losses_mvar': float,
            'loss_percentage': float,
            'total_generation_mw': float
        }
    """
    if not net.converged:
        return {'error': 'Power flow did not converge'}
    
    # Line losses
    line_losses_mw = float(net.res_line.pl_mw.sum())
    line_losses_mvar = float(net.res_line.ql_mvar.sum())
    
    # Transformer losses
    trafo_losses_mw = 0.0
    trafo_losses_mvar = 0.0
    if len(net.trafo) > 0:
        trafo_losses_mw = float(net.res_trafo.pl_mw.sum())
        trafo_losses_mvar = float(net.res_trafo.ql_mvar.sum())
    
    # Total
    total_losses_mw = line_losses_mw + trafo_losses_mw
    total_losses_mvar = line_losses_mvar + trafo_losses_mvar
    
    # Generation
    total_generation_mw = 0.0
    if len(net.res_gen) > 0:
        total_generation_mw += float(net.res_gen.p_mw.sum())
    if len(net.res_ext_grid) > 0:
        total_generation_mw += float(net.res_ext_grid.p_mw.sum())
    
    loss_percentage = (total_losses_mw / total_generation_mw * 100) if total_generation_mw > 0 else 0.0
    
    return {
        'total_losses_mw': total_losses_mw,
        'total_losses_mvar': total_losses_mvar,
        'line_losses_mw': line_losses_mw,
        'line_losses_mvar': line_losses_mvar,
        'trafo_losses_mw': trafo_losses_mw,
        'trafo_losses_mvar': trafo_losses_mvar,
        'loss_percentage': loss_percentage,
        'total_generation_mw': total_generation_mw
    }


def summarize_network(net: pp.pandapowerNet) -> Dict:
    """
    Get network element counts and basic statistics.
    
    Args:
        net: pandapower network
        
    Returns:
        dict: {
            'name': str,
            'elements': {
                'buses': int,
                'lines': int,
                'transformers': int,
                'loads': int,
                'generators': int,
                'ext_grids': int
            },
            'results': {  # only if converged
                'converged': bool,
                'min_voltage': float,
                'max_voltage': float,
                'max_line_loading': float,
                'max_trafo_loading': float
            }
        }
    """
    summary = {
        'name': net.name if hasattr(net, 'name') else 'Unnamed',
        'elements': {
            'buses': len(net.bus),
            'lines': len(net.line),
            'transformers': len(net.trafo),
            'loads': len(net.load),
            'generators': len(net.gen),
            'ext_grids': len(net.ext_grid)
        }
    }
    
    if hasattr(net, 'converged') and net.converged:
        summary['results'] = {
            'converged': True,
            'min_voltage': float(net.res_bus.vm_pu.min()),
            'max_voltage': float(net.res_bus.vm_pu.max()),
            'max_line_loading': float(net.res_line.loading_percent.max()) if len(net.res_line) > 0 else 0.0,
            'max_trafo_loading': float(net.res_trafo.loading_percent.max()) if len(net.trafo) > 0 else 0.0
        }
    
    return summary


def analyze_network(
    net: pp.pandapowerNet,
    v_min: float = 0.95,
    v_max: float = 1.05,
    loading_limit: float = 100.0
) -> Dict:
    """
    Complete network analysis combining summary, violations, and losses.
    
    This is the main function agents should use for comprehensive analysis.
    
    Args:
        net: pandapower network
        v_min: Minimum voltage limit (p.u.)
        v_max: Maximum voltage limit (p.u.)
        loading_limit: Maximum loading limit (%)
        
    Returns:
        dict: Combined results from summarize_network, check_violations, and calculate_losses
    """
    # Run power flow if not already done
    if not hasattr(net, 'converged'):
        try:
            pp.runpp(net)
        except Exception as e:
            return {
                'error': f'Power flow failed: {str(e)}',
                'converged': False
            }
    
    if not net.converged:
        return {
            'error': 'Power flow did not converge',
            'converged': False
        }
    
    return {
        'summary': summarize_network(net),
        'violations': check_violations(net, v_min, v_max, loading_limit),
        'losses': calculate_losses(net)
    }


def print_analysis_report(analysis_results: Dict):
    """
    Print a formatted report from analyze_network results.
    
    Args:
        analysis_results: Dict returned by analyze_network()
    """
    if 'error' in analysis_results:
        print(f"ERROR: {analysis_results['error']}")
        return
    
    summary = analysis_results['summary']
    violations = analysis_results['violations']
    losses = analysis_results['losses']
    
    print("="*60)
    print(f"Network Analysis: {summary['name']}")
    print("="*60)
    
    print("\nNetwork Elements:")
    for key, value in summary['elements'].items():
        print(f"  {key:15s}: {value}")
    
    if 'results' in summary:
        print(f"\nPower Flow: CONVERGED")
        print(f"  Voltage range: {summary['results']['min_voltage']:.4f} - {summary['results']['max_voltage']:.4f} p.u.")
        print(f"  Max line loading: {summary['results']['max_line_loading']:.1f}%")
        if summary['elements']['transformers'] > 0:
            print(f"  Max trafo loading: {summary['results']['max_trafo_loading']:.1f}%")
    
    print("\nViolations:")
    if violations['has_violations']:
        v = violations['voltage']
        if v['undervoltage_buses']:
            print(f"  ⚠️  Undervoltage: {len(v['undervoltage_buses'])} buses")
        if v['overvoltage_buses']:
            print(f"  ⚠️  Overvoltage: {len(v['overvoltage_buses'])} buses")
        
        l = violations['loading']
        if l['overloaded_lines']:
            print(f"  ⚠️  Overloaded lines: {len(l['overloaded_lines'])}")
        if l['overloaded_trafos']:
            print(f"  ⚠️  Overloaded transformers: {len(l['overloaded_trafos'])}")
    else:
        print("  ✓ No violations")
    
    print("\nSystem Losses:")
    print(f"  Total: {losses['total_losses_mw']:.2f} MW ({losses['loss_percentage']:.2f}%)")
    print(f"  Lines: {losses['line_losses_mw']:.2f} MW")
    if summary['elements']['transformers'] > 0:
        print(f"  Transformers: {losses['trafo_losses_mw']:.2f} MW")
    
    print("="*60)


# Backward compatibility - keep old function names as aliases
def run_comprehensive_check(net, v_min=0.95, v_max=1.05, loading_limit=100.0, verbose=True):
    """Legacy function - use analyze_network() instead."""
    results = analyze_network(net, v_min, v_max, loading_limit)
    if verbose:
        print_analysis_report(results)
    return results


def calculate_system_losses(net):
    """Legacy function - use calculate_losses() instead."""
    return calculate_losses(net)


def print_network_summary(net, include_results=True):
    """Legacy function - use print_analysis_report(analyze_network(net)) instead."""
    if include_results:
        results = analyze_network(net)
        print_analysis_report(results)
    else:
        summary = summarize_network(net)
        print("="*60)
        print(f"Network: {summary['name']}")
        print("="*60)
        print("\nNetwork Elements:")
        for key, value in summary['elements'].items():
            print(f"  {key:15s}: {value}")
        print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python network_analysis.py <network_file.json>")
        print("\nExample:")
        print("  python network_analysis.py case39.json")
        sys.exit(1)
    
    network_file = sys.argv[1]
    
    print(f"Loading network from {network_file}...")
    net = pp.from_json(network_file)
    
    print("Running power flow...")
    pp.runpp(net)
    
    # Run and print analysis
    results = analyze_network(net)
    print_analysis_report(results)
