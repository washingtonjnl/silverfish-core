"""Services: the use cases that orchestrate the ports.

Each service contains the flow logic (e.g. import, edit, convert, send) and
talks only to port interfaces — never to a concrete adapter or any framework.
"""
