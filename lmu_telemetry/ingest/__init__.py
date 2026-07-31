"""Reading and normalising session files.

This is the only layer that knows the game's file format exists. Everything it
produces is plain numpy arrays plus small dataclasses, which is what lets a live
data source be added later without touching `analysis`.
"""
