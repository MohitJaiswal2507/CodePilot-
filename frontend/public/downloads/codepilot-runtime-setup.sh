#!/usr/bin/env bash
set -e
echo "=== CodePilot Local Runtime Setup (macOS / Linux) ==="
if ! command -v docker &> /dev/null; then
    echo "Docker is required. Please install Docker from https://www.docker.com/"
    exit 1
fi
echo "Docker CLI found."
if ! docker info &> /dev/null; then
    echo "Docker daemon is not running. Please start Docker first."
    exit 1
fi
echo "Docker daemon is running."
echo "Pulling standard CodePilot language images..."
docker pull python:3.12-slim
docker pull eclipse-temurin:21-jdk
docker pull gcc:14
echo "Done! Run the runtime with: python3 -m runtime.server"
