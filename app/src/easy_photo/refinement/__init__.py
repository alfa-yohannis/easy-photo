"""Refinement: the steps that change a photo, the pipelines made of them, and typed commands.

A :class:`~easy_photo.refinement.pipeline.RefinementPipeline` is a named list
of :class:`~easy_photo.refinement.steps.RefinementStep` objects. Pipelines are
built from references (the user's history, the internet, examples) or from
commands the user types, such as "brighter, more contrast".
"""
