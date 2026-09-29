"""Canales de LISTEN/NOTIFY (ADR-0002). Productores y consumidores importan el nombre
de aquí para que no diverjan.

Un NOTIFY dentro de una transacción solo se entrega si esa transacción confirma: un
consumidor nunca despierta por filas que terminaron en rollback. Pero NOTIFY no es
duradero (si nadie escucha, se pierde), por eso los workers también consultan cada 5 s.
"""

# La API avisa al worker evaluador de que hay lecturas nuevas en ingest.evaluation_queue.
# Sin payload: el evaluador toma filas con SKIP LOCKED, no necesita saber cuáles.
EVALUATION_QUEUE = "vigia_evaluation_queue"

# El evaluador y los workers avisan al dispatcher de que hay alertas pendientes en
# core.alerts. Sin payload, por la misma razón: el dispatcher las toma con SKIP LOCKED.
ALERTS = "vigia_alerts"
