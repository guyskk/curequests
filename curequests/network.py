from curio import ssl, socket


async def ssl_wrap_socket(
    sock, ssl_context,
    do_handshake_on_connect=True,
    server_hostname=None,
    alpn_protocols=None,
):
    if not server_hostname:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    if alpn_protocols:
        ssl_context.set_alpn_protocols(alpn_protocols)
    sock = await ssl_context.wrap_socket(
        sock,
        do_handshake_on_connect=do_handshake_on_connect,
        server_hostname=server_hostname)
    return sock


async def open_connection(
        # socket.create_connection params
        host, port,
        timeout=None,
        source_addr=None,
        # SSLContext.wrap_socket params
        ssl_context=None,
        do_handshake_on_connect=True,
        server_hostname=None,
        alpn_protocols=None,
):
    sock = await socket.create_connection(
        (host, port), timeout, source_addr)
    if not ssl_context:
        return sock
    return await ssl_wrap_socket(
        sock, ssl_context,
        do_handshake_on_connect=do_handshake_on_connect,
        server_hostname=server_hostname,
        alpn_protocols=alpn_protocols,
    )
