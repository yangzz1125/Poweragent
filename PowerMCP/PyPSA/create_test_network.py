import pypsa

def create_simple_network():
    # Initialize a new network
    network = pypsa.Network()

    # Add 3 buses (380 kV)
    network.add("Bus", "Bus 1", v_nom=380)
    network.add("Bus", "Bus 2", v_nom=380)
    network.add("Bus", "Bus 3", v_nom=380)

    # Add a generator at Bus 1 (Slack bus)
    network.add("Generator", "Gen 1", bus="Bus 1", p_nom=1000, control="Slack")

    # Add a load at Bus 3 (500 MW active, 100 MVAR reactive)
    network.add("Load", "Load 1", bus="Bus 3", p_set=500, q_set=100)

    # Add transmission lines connecting the buses
    network.add("Line", "Line 1-2", bus0="Bus 1", bus1="Bus 2", x=0.1, r=0.01, s_nom=1000)
    network.add("Line", "Line 2-3", bus0="Bus 2", bus1="Bus 3", x=0.1, r=0.01, s_nom=1000)

    # Run a quick power flow to ensure it works
    network.pf()
    print("Power flow successful!")
    print("Bus voltages:")
    print(network.buses_t.v_mag_pu)

    # Save the network to a NetCDF file
    output_path = "PyPSA/simple_network.nc"
    network.export_to_netcdf(output_path)
    print(f"\nNetwork successfully saved to {output_path}")

if __name__ == "__main__":
    create_simple_network()
