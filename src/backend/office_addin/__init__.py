"""Stacks inside Microsoft Office: one-click setup and hosting of the add-in.

The add-in (``src/office-addin/``) is a task pane Word, Excel and PowerPoint
load beside the document. Office owns the file; the pane reads the
selection, asks Stacks, and writes text back through Office's own API.

Office will only load a pane over HTTPS from the URLs in a registered
manifest, so "connect Office" does four things, all per-user and without
admin rights (``service.connect``):

1. issue a certificate for ``localhost`` (``certs``) — a throwaway local CA
   signs it and the CA's key is discarded, so nothing can mint more;
2. ask the platform to trust that CA (per-user Windows roots or Mac keychain);
3. write the manifest with this machine's port and register it with Office
   (``manifest`` and the Windows or macOS registration adapter);
4. serve the pane and the ``/office`` bridge from the backend itself over
   HTTPS on a fixed port (``host``), same-origin, so there is no second
   server, no CORS, and nothing extra to launch.

While Stacks runs, the host runs; the Stacks button in Office works while
the Stacks app is open.
"""
