#!/usr/bin/env python3
"""
N-1 Contingency Analysis for pandapower networks.

This module provides functions for agent-driven contingency analysis.
Returns structured data suitable for automated decision-making.

Typical usage:
    import pandapower as pp
    from contingency_analysis import analyze_single_contingency, analyze_n1
    
    net = pp.from_json("network.json")
    results = analyze_n1(net)
    critical = [r for r in results if r['critical']]
"""

import pandapower as pp
import pandas as pd
from typing import Dict, List, Optional


def analyze_single_contingency(
    net: pp.pandapowerNet,
    element_type: str,
    element_idx: int,
    v_min: float = 0.95,
    v_max: float = 1.05,
    loading_limit: float = 100.0
) -> Dict:
    """
    Analyze a single N-1 contingency by removing one element.
    
    Args:
        net: pandapower network (will be copied, original unchanged)
        element_type: 'line', 'trafo', or 'trafo3w'
        element_idx: Element index to remove
        v_min: Minimum voltage limit (p.u.)
        v_max: Maximum voltage limit (p.u.)
        loading_limit: Maximum loading limit (%)
        
    Returns:
        dict: {
            'element_type': str,
            'element_idx': int,
            'converged': bool,
            'critical': bool,  # True if diverged or has violations
            'voltage_violations': list of bus indices,
            'line_overloads': list of line indices,
            'trafo_overloads': list of trafo indices,
            'min_voltage': float (if converged),
            'max_voltage': float (if converged),
            'max_loading': float (if converged)
        }
    """
    # Create copy and disconnect element
    net_copy = net.deepcopy()
    net_copy[element_type].at[element_idx, 'in_service'] = False
    
    # Run power flow
    try:
        pp.runpp(net_copy)
    except Exception as e:
        return {
            'element_type': element_type,
            'element_idx': element_idx,
            'converged': False,
            'critical': True,
            'error': str(e)
        }
    
    if not net_copy.converged:
        return {
            'element_type': element_type,
            'element_idx': element_idx,
            'converged': False,
            'critical': True
        }
    
    # Check violations
    voltage_violations = net_copy.res_bus[
        (net_copy.res_bus.vm_pu < v_min) | (net_copy.res_bus.vm_pu > v_max)
    ].index.tolist()
    
    line_overloads = []
    if len(net_copy.res_line) > 0:
        line_overloads = net_copy.res_line[
            net_copy.res_line.loading_percent > loading_limit
        ].index.tolist()
    
    trafo_overloads = []
    if len(net_copy.res_trafo) > 0:
        trafo_overloads = net_copy.res_trafo[
            net_copy.res_trafo.loading_percent > loading_limit
        ].index.tolist()
    
    critical = bool(voltage_violations or line_overloads or trafo_overloads)
    
    return {
        'element_type': element_type,
        'element_idx': element_idx,
        'converged': True,
        'critical': critical,
        'voltage_violations': voltage_violations,
        'line_overloads': line_overloads,
        'trafo_overloads': trafo_overloads,
        'min_voltage': float(net_copy.res_bus.vm_pu.min()),
        'max_voltage': float(net_copy.res_bus.vm_pu.max()),
        'max_loading': float(max(
            net_copy.res_line.loading_percent.max() if len(net_copy.res_line) > 0 else 0,
            net_copy.res_trafo.loading_percent.max() if len(net_copy.res_trafo) > 0 else 0
        ))
    }


def analyze_n1(
    net: pp.pandapowerNet,
    elements: List[str] = ['line', 'trafo'],
    v_min: float = 0.95,
    v_max: float = 1.05,
    loading_limit: float = 100.0
) -> List[Dict]:
    """
    Run N-1 contingency analysis for specified element types.
    
    This is the main function agents should use for N-1 analysis.
    
    Args:
        net: pandapower network
        elements: List of element types to analyze ('line', 'trafo', 'trafo3w')
        v_min: Minimum voltage limit (p.u.)
        v_max: Maximum voltage limit (p.u.)
        loading_limit: Maximum loading limit (%)
        
    Returns:
        list of dicts: One dict per contingency with results from analyze_single_contingency
    """
    results = []
    
    # Analyze line contingencies
    if 'line' in elements:
        for idx in net.line.index:
            result = analyze_single_contingency(net, 'line', idx, v_min, v_max, loading_limit)
            results.append(result)
    
    # Analyze transformer contingencies
    if 'trafo' in elements and len(net.trafo) > 0:
        for idx in net.trafo.index:
            result = analyze_single_contingency(net, 'trafo', idx, v_min, v_max, loading_limit)
            results.append(result)
    
    # Analyze 3-winding transformer contingencies
    if 'trafo3w' in elements and len(net.trafo3w) > 0:
        for idx in net.trafo3w.index:
            result = analyze_single_contingency(net, 'trafo3w', idx, v_min, v_max, loading_limit)
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
            'secure': int
        }
    """
    total = len(results)
    converged = sum(1 for r in results if r.get('converged', False))
    diverged = total - converged
    critical = sum(1 for r in results if r.get('critical', False))
    secure = total - critical
    
    return {
        'total': total,
        'converged': converged,
        'diverged': diverged,
        'critical': critical,
        'secure': secure
    }


def print_n1_report(results: List[Dict], verbose: bool = True):
    """
    Print formatted N-1 analysis report.
    
    Args:
        results: List of dicts from analyze_n1()
        verbose: If True, show details of critical contingencies
    """
    summary = summarize_n1_results(results)
    
    print("="*70)
    print("N-1 CONTINGENCY ANALYSIS REPORT")
    print("="*70)
    
    print(f"\nTotal contingencies:    {summary['total']}")
    print(f"Converged:              {summary['converged']}")
    print(f"Diverged:               {summary['diverged']}")
    print(f"Critical:               {summary['critical']}")
    print(f"Secure:                 {summary['secure']}")
    
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
        for r in critical:
            print(f"\n{r['element_type'].upper()} {r['element_idx']}:")
            
            if not r['converged']:
                print("  ⚠️  Power flow DIVERGED")
                if 'error' in r:
                    print(f"     Error: {r['error']}")
            else:
                if r['voltage_violations']:
                    print(f"  ⚠️  Voltage violations at {len(r['voltage_violations'])} buses")
                    print(f"     Min: {r['min_voltage']:.4f} p.u., Max: {r['max_voltage']:.4f} p.u.")
                
                if r['line_overloads']:
                    print(f"  ⚠️  {len(r['line_overloads'])} overloaded lines")
                
                if r['trafo_overloads']:
                    print(f"  ⚠️  {len(r['trafo_overloads'])} overloaded transformers")
                
                if r.get('max_loading', 0) > 0:
                    print(f"     Max loading: {r['max_loading']:.1f}%")
    
    print("\n" + "="*70)


# Backward compatibility - old function names
def run_n1_analysis(net, elements=['line', 'trafo'], v_min=0.95, v_max=1.05, 
                    loading_limit=100.0, verbose=True):
    """Legacy function - use analyze_n1() instead."""
    results = analyze_n1(net, elements, v_min, v_max, loading_limit)
    if verbose:
        print_n1_report(results, verbose=True)
    
    # Convert to DataFrame for backward compatibility
    df = pd.DataFrame(results)
    return df


def generate_contingency_report(results_df, output_file=None):
    """Legacy function - use print_n1_report() instead."""
    if isinstance(results_df, pd.DataFrame):
        results = results_df.to_dict('records')
    else:
        results = results_df
    
    # Generate text report
    from io import StringIO
    import sys
    
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    
    print_n1_report(results, verbose=True)
    
    report = sys.stdout.getvalue()
    sys.stdout = old_stdout
    
    if output_file:
        with open(output_file, 'w') as f:
            f.write(report)
        print(f"Report saved to: {output_file}")
    
    return report


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python contingency_analysis.py <network_file.json>")
        print("\nExample:")
        print("  python contingency_analysis.py case39.json")
        sys.exit(1)
    
    network_file = sys.argv[1]
    
    # Load network
    print(f"Loading network from {network_file}...")
    net = pp.from_json(network_file)
    
    # Run baseline power flow
    print("Running baseline power flow...")
    pp.runpp(net)
    
    if not net.converged:
        print("ERROR: Baseline power flow did not converge!")
        sys.exit(1)
    
    print(f"Baseline converged")
    print(f"Network: {len(net.bus)} buses, {len(net.line)} lines, {len(net.trafo)} transformers\n")
    
    # Run N-1 analysis
    print("Running N-1 analysis...")
    results = analyze_n1(net, elements=['line', 'trafo'])
    
    # Print report
    print_n1_report(results, verbose=True)
    
    # Save to file
    with open('contingency_report.txt', 'w') as f:
        old_stdout = sys.stdout
        sys.stdout = f
        print_n1_report(results, verbose=True)
        sys.stdout = old_stdout
    
    print(f"\nReport saved to: contingency_report.txt")
