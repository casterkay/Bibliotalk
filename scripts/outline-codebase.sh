#!/bin/bash
tree packages/ -I "*.egg-info" -I __pycache__ -I tests -I build -I ".*" -L 5 > CODEBASE.txt
tree services/ -I "*.egg-info" -I __pycache__ -I tests -I build -I ".*" -L 5 >> CODEBASE.txt