import json, sys
connections = json.load(sys.stdin)
if 'pick: pg load material' in connections:
    connections['pick: pg load material']['main'] = [
        [{"node": "pick: build examiner body", "type": "main", "index": 0}]
    ]
    connections['pick: build examiner body'] = {
        "main": [
            [{"node": "pick: Examiner (Haiku)", "type": "main", "index": 0}]
        ]
    }
    sys.stderr.write("Rewired pick chain: pg load -> build body -> Examiner\n")
sys.stdout.write(json.dumps(connections))
