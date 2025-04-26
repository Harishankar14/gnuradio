#!/usr/bin/env python
# Copyright 2021 Free Software Foundation, Inc.
# Copyright 2025 Harishankar 
# This file is part of GNU Radio
# SPDX-License-Identifier: GPL-3.0-or-later
from gnuradio import gr, gr_unittest, blocks, network
import socket
import threading
import time


class qa_tcp_sink(gr_unittest.TestCase):

    def setUp(self):
        self.tb = gr.top_block()
        self.port = 2003  # Port > 1024 for test
        self.received_data = bytearray()

    def tcp_client_read(self):
        """Client will repeatedly try to connect to tcp_sink and retrieve the test data"""
        #FIXME this behavior seems too complicated for a simple test case
        retries = 30
        for attempt in range(retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(('127.0.0.1', self.port))
                    received = b''
                    while len(received) < 5:
                        chunk = s.recv(5)
                        if not chunk:
                            break
                        received += chunk
                    self.received_data = list(received)
                    return
            except (ConnectionRefusedError, OSError) as e:
                time.sleep(0.1)
        raise ConnectionError("Client could not connect to tcp_sink")

    def tcp_client(self, test_data):
        """Client will connect to tcp_sink and send the test data."""
        time.sleep(0.1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect(('localhost', self.port))
            client_socket.sendall(test_data)
            client_socket.close()

    def tcp_server(self):
        """TCP Server to receive and store data sent by tcp_sink."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('localhost', self.port))
            server_socket.listen(1)
            client_socket, _ = server_socket.accept()
            with client_socket:
                while True:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    self.received_data.extend(data)

    def tearDown(self):
        self.tb = None
        self.received_data = bytearray()  # Reset received data for the next test

    @gr_unittest.unittest.skip("FIXME")
    def test_tcp_sink_server_mode(self):
        """Test tcp_sink in server mode with a tcp client retrieving known data."""
        # Known data to send
        test_data = list(b'hello world')

        #FIXME add some kind of synchronizer between vector source and sink,
        # remove repeat sending behavior from vector

        # Create the GNU Radio flowgraph with tcp_sink in server mode
        tcp_sink = network.tcp_sink(gr.sizeof_char, 1, '127.0.0.1', self.port, 2)  # Server mode
        vector_source = blocks.vector_source_b(test_data, True)
        self.tb.connect( vector_source, tcp_sink)

        # Start the flowgraph
        self.tb.start()

        #FIXME simplify tcp_client_read if using a synchronizer, no need to repeatedly retry connections

        # Startup a tcp client to connect
        client_thread = threading.Thread(target=self.tcp_client_read, daemon=True)
        client_thread.start()
        client_thread.join()

        # Stop the flowgraph after the data transfer
        self.tb.stop()
        self.tb.wait()

        self.assertEqual(self.received_data, test_data)

    def test_tcp_sink_client_mode(self):
        """Test tcp_sink in client mode (server=False) by sending known data."""
        # Start TCP Server in background thread
        server_thread = threading.Thread(target=self.tcp_server, daemon=True)
        server_thread.start()
        time.sleep(0.1)  # Ensure server is ready before starting flowgraph

        # Known data to send
        test_data = list(b'hello world')

        # Create the GNU Radio flowgraph
        vector_source = blocks.vector_source_b(test_data, False)
        tcp_sink = network.tcp_sink(gr.sizeof_char, 1, '127.0.0.1', self.port, 1)
        self.tb.connect(vector_source, tcp_sink)

        # Run the flowgraph
        self.tb.start()
        time.sleep(0.1)  # Allow time for data transfer
        self.tb.stop()
        self.tb.wait()

        self.assertEqual(self.received_data, bytearray(test_data))

    def tcp_receive(self, serversocket):
        """Helper function to receive data from tcp_sink."""
        client_socket, _ = serversocket.accept()
        with client_socket:
            while True:
                data = client_socket.recv(4096)
                if not data:
                    break
                self.received_data.extend(data)

    def test_restart(self):
        """Test restarting the GNU Radio flowgraph with tcp_sink."""
        serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serversocket.settimeout(30.0)  # Set a timeout to prevent indefinite blocking
        serversocket.bind(('localhost', self.port))
        serversocket.listen()

        # Start a thread to receive data
        thread = threading.Thread(target=self.tcp_receive, args=(serversocket,))
        thread.start()

        # Create the GNU Radio flowgraph
        null_source = blocks.null_source(gr.sizeof_gr_complex)
        throttle = blocks.throttle(gr.sizeof_gr_complex, 320000, True)
        tcp_sink = network.tcp_sink(gr.sizeof_gr_complex, 1, '127.0.0.1', self.port, 1)
        self.tb.connect(null_source, throttle, tcp_sink)

        # Start, stop, and restart the flowgraph
        self.tb.start()
        time.sleep(0.1)  # Allow some time for data flow
        self.tb.stop()
        time.sleep(0.1)  # Short pause before restarting
        self.tb.start()
        time.sleep(0.1)
        self.tb.stop()

        # Ensure thread completes and clean up
        thread.join()
        serversocket.close()

    @gr_unittest.unittest.skip("FIXME")
    def test_tcp_server_client(self):
        """Test tcp source(server=True) and sink(client=True) blocks end-to-end. """
        # Create known data to send. Sink block will push this later.
        test_data = list(b'hello world')

        # Create vector_sink to catch known data. Will be connected with source later.
        vector_sink = blocks.vector_sink_b()

        # Create a source flowgraph function to be used in a thread later
        def setup_source_flowgraph():
            source_tb = gr.top_block()
            # tcp source constructor blocks till it can bind to a client in server mode
            tcp_source = network.tcp_source.tcp_source(
                itemsize=gr.sizeof_char, addr='127.0.0.1', port=self.port, server=True)

            # connect and run flowgraph after successful bind
            source_tb.connect(tcp_source, vector_sink)
            source_tb.start()
            time.sleep(0.1) # pause for flowgraph to catch data
            source_tb.stop()
            source_tb.wait()

            #FIXME tcp_source is not releasing the port after use

        # Start source flowgraph in a thread
        source_thread = threading.Thread(target=setup_source_flowgraph)
        source_thread.start()

        # Create sink flowgraph
        sink_tb = gr.top_block()
        tcp_sink = network.tcp_sink(gr.sizeof_char, 1, '127.0.0.1', self.port, 1)
        vector_source = blocks.vector_source_b(test_data, repeat=False)
        sink_tb.connect(vector_source, tcp_sink)
        # Start sink flowgraph
        sink_tb.start()
        time.sleep(0.1) # pause for flowgraph to push data

        # Cleanup
        sink_tb.stop()
        sink_tb.wait()
        source_thread.join()

        # Validate data caught by source flowgraph
        received_data = vector_sink.data()
        self.assertEqual(list(received_data), test_data)

    @gr_unittest.unittest.skip("FIXME")
    def test_tcp_client_server(self):
        """Test tcp source(client=True) and sink(server=True) blocks end-to-end. """
        # Create known data to send. Sink block will push this later.
        test_data = list(b'hello world')
        expected_len = len(test_data)

        # Create vector_sink to catch known data. Will be connected with source later.
        vector_sink = blocks.vector_sink_b()

        #FIXME add some kind of synchronizer between vector source and sink,
        # remove repeat sending behavior from vector

        # Start server sink flowgraph
        sink_tb = gr.top_block()
        vector_source = blocks.vector_source_b(test_data, repeat=True)
        throttle_block = blocks.throttle(gr.sizeof_char, 100000)
        tcp_sink = network.tcp_sink(gr.sizeof_char, 1, '127.0.0.1', self.port, 2)  # server=True
        sink_tb.connect(vector_source, throttle_block, tcp_sink)
        sink_tb.start()
        time.sleep(0.1) # pause briefly for sink to bind

        # Start client source flowgraph
        source_tb = gr.top_block()
        tcp_source = network.tcp_source.tcp_source(
            itemsize=gr.sizeof_char, addr='127.0.0.1', port=self.port, server=False)  # client mode
        source_tb.connect(tcp_source, vector_sink)
        source_tb.start()
        time.sleep(1) # pause longer for client to connect

        # FIXME tcp_source is not releasing the port after use

        # Cleanup
        source_tb.stop()
        source_tb.wait()
        sink_tb.stop()
        sink_tb.wait()

        # FIXME simplify validation behavior, no need to search given better synchronization

        # Get data from source flowgraph
        received_data = list(vector_sink.data())
        # Search the received data packets for a single test data sequence
        haystack, needle = received_data, test_data
        found_test_data = False
        for i in range(len(haystack) - len(needle) + 1):
            if haystack[i:i + len(needle)] == needle:
                found_test_data = True

        self.assertTrue(found_test_data)


if __name__ == '__main__':
    gr_unittest.run(qa_tcp_sink)
