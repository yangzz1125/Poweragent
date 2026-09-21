#!/usr/bin/env python3
"""
N-1 Contingency Analysis for PyPSA networks.

This module provides functions for agent-driven contingency analysis on PyPSA networks.
Returns structured data suitable for automated decision-making.

Typical usage:
    import pypsa
    from contingency_analysis import analyze_single_contingency, analyze_n1
    
    network = pypsa.Network("network.nc")
    network.optimize()  # Get baseline solution
    
    results = analyze_n1(network)
    critical = [r for r in results if r['critical']]
"""

import pypsa
import pandas as pd
from typing import Dict, List, Optional


def analyze_single_contingency(
    network: pypsa.Network,
    element_type: str,
    element_name: str,
    method: str = 'optimize'
) -> Dict:
    """
    Analyze a single N-1 contingency by removing one element.
    
    Args:
        network: PyPSA Network object (will be copied, original unchanged)
        element_type: 'line' or 'link'
        element_name: Element name/index to remove
        method: 'optimize' for re-optimization, 'lpf' for power flow only
        
    Returns:
        dict: {
            'element_type': str,
            'element_name': str,
            'converged': bool,
            'critical': bool,  # True if failed or violations
            'objective': float (if converged),
            'objective_increase': float (if baseline available),
            'voltage_violations': list of bus names,
            'overloaded_lines': list of line names,
            'overloaded_links': list of link names,
            'line_loading': {line_name: max_loading_pct, ...},
            'link_loading': {link_name: max_loading_pct, ...}
        }
    """
    # Create copy
    net_copy = network.deepcopy()
    
    # Store original objective if available
    baseline_objective = network.objective if hasattr(network, 'objective') else None
    
    # Remove element
    if element_type == 'line':
        if element_name not in net_copy.lines.index:
            return {
                'element_type': element_type,
                'element_name': element_name,
                'converged': False,
                'critical': True,
                'error': f'Line {element_name} not found'
            }
        net_copy.mremove("Line", element_name)
    
    elif element_type == 'link':
        if element_name not in net_copy.links.index:
            return {
                'element_type': element_type,
                'element_name': element_name,
                'converged': False,
                'critical': True,
                'error': f'Link {element_name} not found'
            }
        net_copy.mremove("Link", element_name)
    
    else:
        return {
            'element_type': element_type,
            'element_name': element_name,
            'converged': False,
            'critical': True,
            'error': f'Invalid element type: {element_type}'
        }
    
    # Run analysis
    try:
        if method == 'optimize':
            net_copy.optimize()
        elif method == 'lpf':
            net_copy.lpf()
        else:
            return {
                'element_type': element_type,
                'element_name': element_name,
                'converged': False,
                'critical': True,
                'error': f'Invalid method: {method}'
            }
    except Exception as e:
        return {
            'element_type': element_type,
            'element_name': element_name,
            'converged': False,
            'critical': True,
            'error': str(e)
        }
    
    # Check convergence
    if method == 'optimize':
        converged = hasattr(net_copy, 'status') and net_copy.status.get('status') == 'ok'
    else:
        converged = True  # lpf doesn't have status
    
    if not converged:
        return {
            'element_type': element_type,
            'element_name': element_name,
            'converged': False,
            'critical': True
        }
    
    # Check for violations
    voltage_violations = []
    overloaded_lines = []
    overloaded_links = []
    line_loading = {}
    link_loading = {}
    
    # Voltage violations (< 0.95 or > 1.05 p.u.)
    if not net_copy.buses_t.v_mag_pu.empty:
        for bus in net_copy.buses.index:
            if bus in net_copy.buses_t.v_mag_pu.columns:
                v_min = net_copy.buses_t.v_mag_pu[bus].min()
                v_max = net_copy.buses_t.v_mag_pu[bus].max()
                if v_min < 0.95 or v_max > 1.05:
                    voltage_violations.append(bus)
    
    # Line overloading
    if not net_copy.lines_t.p0.empty:
        for line in net_copy.lines.index:
            if line in net_copy.lines_t.p0.columns:
                p_flow = net_copy.lines_t.p0[line].abs()
                s_nom = net_copy.lines.at[line, 's_nom']
                
                if s_nom > 0:
                    loading = (p_flow / s_nom * 100)
                    max_loading = float(loading.max())
                    line_loading[line] = max_loading
                    
                    if max_loading > 100:
                        overloaded_lines.append(line)
    
    # Link overloading
    if not net_copy.links_t.p0.empty:
        for link in net_copy.links.index:
            if link in net_copy.links_t.p0.columns:
                p_flow = net_copy.links_t.p0[link].abs()
                p_nom = net_copy.links.at[link, 'p_nom']
                
                if p_nom > 0:
                    loading = (p_flow / p_nom * 100)
                    max_loading = float(loading.max())
                    link_loading[link] = max_loading
                    
                    if max_loading > 100:
                        overloaded_links.append(link)
    
    critical = bool(voltage_violations or overloaded_lines or overloaded_links)
    
    result = {
        'element_type': element_type,
        'element_name': element_name,
        'converged': True,
        'critical': critical,
        'voltage_violations': voltage_violations,
        'overloaded_lines': overloaded_lines,
        'overloaded_links': overloaded_links,
        'line_loading': line_loading,
        'link_loading': link_loading
    }
    
    # Add objective information if available
    if method == 'optimize' and hasattr(net_copy, 'objective'):
        result['objective'] = float(net_copy.objective)
        if baseline_objective is not None:
            result['objective_increase'] = float(net_copy.objective - baseline_objective)
            result['objective_increase_pct'] = float((net_copy.objective - baseline_objective) / baseline_objective * 100)
    
    return result


def analyze_n1(
    network: pypsa.Network,
    elements: List[str] = ['line', 'link'],
    method: str = 'optimize'
) -> List[Dict]:
    """
    Run N-1 contingency analysis for specified element types.
    
    This is the main function agents should use for N-1 analysis.
    
    Args:
        network: PyPSA Network object
        elements: List of element types to analyze ('line', 'link')
        method: 'optimize' for re-optimization, 'lpf' for linear power flow only
        
    Returns:
        list of dicts: One dict per contingency with results from analyze_single_contingency
    """
    results = []
    
    # Analyze line contingencies
    if 'line' in elements:
        for line in network.lines.index:
            result = analyze_single_contingency(network, 'line', line, method)
            results.append(result)
    
    # Analyze link contingencies
    if 'link' in elements:
        for link in network.links.index:
            result = analyze_single_contingency(network, 'link', link, method)
            results.append(result)
    
    return results


def get_critical_contingencies(results: List[Dict]) -> List[Dict]:
    """
    Filter N-1 results to only critical contingencies.
    
    Args:
        results: List of dicts from analyze_n1()
        
    Returns:
        list of dicts: Only contingencies that are critical
    """
    return [r for r in results if r.get('critical', False)]


def get_most_expensive_contingencies(results: List[Dict], top_n: int = 10) -> List[Dict]:
    """
    Get contingencies with largest cost increase.
    
    Args:
        results: List of dicts from analyze_n1()
        top_n: Number of top contingencies to return
        
    Returns:
        list of dicts: Top N most expensive contingencies
    """
    # Filter to converged contingencies with objective increase
    valid = [r for r in results if r.get('converged', False) and 'objective_increase' in r]
    
    # Sort by objective increase
    sorted_results = sorted(valid, key=lambda x: x['objective_increase'], reverse=True)
    
    return sorted_results[:top_n]


def summarize_n1_results(results: List[Dict]) -> Dict:
    """
    Generate summary statistics from N-1 analysis results.
    
    Args:
        results: List of dicts from analyze_n1()
        
    Returns:
        dict: {
            'total': int,
            'converged': int,
            'diverged': int,
            'critical': int,
            'secure': int,
            'max_objective_increase': float,
            'avg_objective_increase': float
        }
    """
    total = len(results)
    converged = sum(1 for r in results if r.get('converged', False))
    diverged = total - converged
    critical = sum(1 for r in results if r.get('critical', False))
    secure = total - critical
    
    summary = {
        'total': total,
        'converged': converged,
        'diverged': diverged,
        'critical': critical,
        'secure': secure
    }
    
    # Calculate objective statistics if available
    objectives = [r['objective_increase'] for r in results if 'objective_increase' in r]
    if objectives:
        summary['max_objective_increase'] = float(max(objectives))
        summary['avg_objective_increase'] = float(sum(objectives) / len(objectives))
    
    return summary


def print_n1_report(results: List[Dict], verbose: bool = True):
    """
    Print formatted N-1 analysis report.
    
    Args:
        results: List of dicts from analyze_n1()
        verbose: If True, show details of critical contingencies
    """
    summary = summarize_n1_results(results)
    
    print("="*70)
    print("PyPSA N-1 CONTINGENCY ANALYSIS REPORT")
    print("="*70)
    
    print(f"\nTotal contingencies:    {summary['total']}")
    print(f"Converged:              {summary['converged']}")
    print(f"Diverged:               {summary['diverged']}")
    print(f"Critical:               {summary['critical']}")
    print(f"Secure:                 {summary['secure']}")
    
    if 'max_objective_increase' in summary:
        print(f"\nCost Impact:")
        print(f"  Max increase:     €{summary['max_objective_increase']:,.0f}")
        print(f"  Average increase: €{summary['avg_objective_increase']:,.0f}")
    
    if summary['critical'] == 0:
        print("\n" + "="*70)
        print("✓ SYSTEM IS N-1 SECURE")
        print("="*70)
        return
    
    print("\n" + "="*70)
    print(f"⚠️  {summary['critical']} CRITICAL CONTINGENCIES FOUND")
    print("="*70)
    
    if verbose:
        critical = get_critical_contingencies(results)
        
        # Show most expensive contingencies first if cost data available
        if any('objective_increase' in r for r in critical):
            critical = sorted([r for r in critical if 'objective_increase' in r],
                            key=lambda x: x.get('objective_increase', 0),
                            reverse=True)
        
        for r in critical[:20]:  # Show top 20
            print(f"\n{r['element_type'].upper()} '{r['element_name']}':")
            
            if not r['converged']:
                print("  ⚠️  DIVERGED")
                if 'error' in r:
                    print(f"     Error: {r['error']}")
            else:
                if 'objective_increase' in r:
                    print(f"  Cost increase: €{r['objective_increase']:,.0f} ({r.get('objective_increase_pct', 0):.1f}%)")
                
                if r['voltage_violations']:
                    print(f"  ⚠️  Voltage violations at {len(r['voltage_violations'])} buses")
                    if len(r['voltage_violations']) <= 5:
                        print(f"     Buses: {', '.join(r['voltage_violations'])}")
                
                if r['overloaded_lines']:
                    print(f"  ⚠️  {len(r['overloaded_lines'])} overloaded lines")
                    top_lines = sorted([(line, r['line_loading'][line]) 
                                       for line in r['overloaded_lines']], 
                                      key=lambda x: x[1], reverse=True)[:3]
                    for line, loading in top_lines:
                        print(f"     {line}: {loading:.1f}%")
                
                if r['overloaded_links']:
                    print(f"  ⚠️  {len(r['overloaded_links'])} overloaded links")
                    top_links = sorted([(link, r['link_loading'][link]) 
                                       for link in r['overloaded_links']], 
                                      key=lambda x: x[1], reverse=True)[:3]
                    for link, loading in top_links:
                        print(f"     {link}: {loading:.1f}%")
        
        if len(critical) > 20:
            print(f"\n... and {len(critical) - 20} more critical contingencies")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python contingency_analysis.py <network_file.nc> [--method optimize|lpf]")
        print("\nExample:")
        print("  python contingency_analysis.py my_network.nc")
        print("  python contingency_analysis.py my_network.nc --method lpf")
        sys.exit(1)
    
    network_file = sys.argv[1]
    method = 'optimize'
    
    if len(sys.argv) > 2 and sys.argv[2] == '--method':
        if len(sys.argv) > 3:
            method = sys.argv[3]
    
    # Load network
    print(f"Loading network from {network_file}...")
    network = pypsa.Network(network_file)
    
    # Run baseline optimization if using optimize method
    if method == 'optimize':
        print("Running baseline optimization...")
        network.optimize()
        
        if not hasattr(network, 'status') or network.status.get('status') != 'ok':
            print("ERROR: Baseline optimization did not converge!")
            sys.exit(1)
        
        print(f"Baseline cost: €{network.objective:,.0f}")
    
    print(f"Network: {len(network.buses)} buses, {len(network.lines)} lines, {len(network.links)} links\n")
    
    # Run N-1 analysis
    print(f"Running N-1 analysis (method: {method})...")
    results = analyze_n1(network, elements=['line', 'link'], method=method)
    
    # Print report
    print_n1_report(results, verbose=True)
    
    # Save detailed results to CSV
    import pandas as pd
    df = pd.DataFrame(results)
    df.to_csv('n1_results.csv', index=False)
    print(f"\nDetailed results saved to: n1_results.csv")
