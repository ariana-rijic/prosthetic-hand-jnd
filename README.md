# Prosthetic Hand JND: Visual Speed Discrimination Test

A Python desktop application for measuring the **just noticeable difference (JND)** in the closing speed of a prosthetic hand, based on visual perception.

Developed as part of my bachelor's thesis in Biomedical Engineering at the Faculty of Technical Sciences, University of Novi Sad:
*"Determining the Just Noticeable Difference in the Closing Speed of a Prosthetic Hand Based on Visual Perception"*.

## Overview

In each trial the participant observes two consecutive hand closings at different speeds and selects which one was faster. An adaptive staircase procedure adjusts the speed difference based on the answers and converges to the participant's discrimination threshold.

The test can be run in two modes:

- **Virtual mode**: an animated hand closing is shown on screen.
- **Physical mode**: the real prosthetic hand (Ottobock Michelangelo) closes and opens, controlled over a Bluetooth serial connection. No animation is shown, so the participant has a single source of speed information.

## Features

- Participant data entry (age, dominant hand, vision correction, test mode)
- Practice phase with 5 trials and correctness feedback
- Main test without feedback
- Adaptive **1-up / 2-down** staircase procedure with decreasing step sizes (4% → 2% → 1%)
- Test ends after 5 reversals, or after 7 correct answers at the minimum difference
- JND estimated as the mean of the last 4 reversals (the first reversal is discarded)
- Response time measurement for every trial
- Results plot showing the staircase progression, reversals and the estimated JND
- Automatic saving of every answer to a CSV file
- Option to stop the test early and view provisional results

## Method

| Parameter | Value |
|---|---|
| Standard speed | 50% |
| Initial difference | 15% |
| Practice difference | 25% |
| Step sizes | 4%, 2%, 1% (reduced after each reversal) |
| Stopping rule | 5 reversals |
| JND calculation | mean of the last 4 reversals |

The order of the standard and comparison stimulus is randomized in every trial.

## Tech stack

- Python 3
- Tkinter (GUI)
- PySerial (Bluetooth SPP communication)

## Installation and running

```bash
pip install -r requirements.txt
python test_vizuelnog_razlikovanja_brzine.py
```

## Output

Results are saved to the `rezultati/` folder as a CSV file per session, including participant data, stimulus speeds, answers, correctness, response times and staircase state after each trial.

## Note on the prosthesis protocol

The communication protocol of the Ottobock Michelangelo hand is confidential. In this public version, the protocol-specific values (command IDs, frame format and byte layout) have been removed. **Virtual mode works fully**, while physical mode requires the original protocol implementation.

## Results

The application was tested with two participants, comparing JND values obtained with the on-screen animation and with the physical prosthesis.

## Author

**Ariana Rijić**
Biomedical Engineer, MSc student in Computing and Automation (Biomedical Engineering track)
Faculty of Technical Sciences, University of Novi Sad
