import unittest

from ovos_workshop.intents import Intent, IntentBuilder


class IntentTest(unittest.TestCase):

    def test_basic_intent(self):
        intent = IntentBuilder("play television intent") \
            .require("PlayVerb") \
            .require("Television Show") \
            .build()
        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False}, {'start_token': 1, 'entities': [
            {'key': 'the big bang theory', 'match': 'the big bang theory',
             'data': [('the big bang theory', 'Television Show')], 'confidence': 1.0}], 'confidence': 1.0,
                                                          'end_token': 4, 'match': 'the big bang theory',
                                                          'key': 'the big bang theory', 'from_context': False}]
        result_intent = intent.validate(tags, 0.95)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('PlayVerb') == 'play'
        assert result_intent.get('Television Show') == "the big bang theory"

    def test_at_least_one(self):
        intent = IntentBuilder("play intent") \
            .require("PlayVerb") \
            .one_of("Television Show", "Radio Station") \
            .build()
        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False}, {'start_token': 1, 'entities': [
            {'key': 'the big bang theory', 'match': 'the big bang theory',
             'data': [('the big bang theory', 'Television Show')], 'confidence': 1.0}], 'confidence': 1.0,
                                                          'end_token': 4, 'match': 'the big bang theory',
                                                          'key': 'the big bang theory', 'from_context': False}]

        result_intent = intent.validate(tags, 0.95)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('PlayVerb') == 'play'
        assert result_intent.get('Television Show') == "the big bang theory"

        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False},
                {'match': 'barenaked ladies', 'key': 'barenaked ladies', 'start_token': 2, 'entities': [
                    {'key': 'barenaked ladies', 'match': 'barenaked ladies',
                     'data': [('barenaked ladies', 'Radio Station')], 'confidence': 1.0}], 'end_token': 3,
                 'from_context': False}]

        result_intent = intent.validate(tags, 0.8)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('PlayVerb') == 'play'
        assert result_intent.get('Radio Station') == "barenaked ladies"

    def test_at_least_on_no_required(self):
        intent = IntentBuilder("play intent") \
            .one_of("Television Show", "Radio Station") \
            .build()
        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False}, {'start_token': 1, 'entities': [
            {'key': 'the big bang theory', 'match': 'the big bang theory',
             'data': [('the big bang theory', 'Television Show')], 'confidence': 1.0}], 'confidence': 1.0,
                                                          'end_token': 4, 'match': 'the big bang theory',
                                                          'key': 'the big bang theory', 'from_context': False}]
        result_intent = intent.validate(tags, 0.9)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('Television Show') == "the big bang theory"

        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False},
                {'match': 'barenaked ladies', 'key': 'barenaked ladies', 'start_token': 2, 'entities': [
                    {'key': 'barenaked ladies', 'match': 'barenaked ladies',
                     'data': [('barenaked ladies', 'Radio Station')], 'confidence': 1.0}], 'end_token': 3,
                 'from_context': False}]

        result_intent = intent.validate(tags, 0.8)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('Radio Station') == "barenaked ladies"

    def test_at_least_one_alone(self):
        intent = IntentBuilder("OptionsForLunch") \
            .one_of("Question", "Command") \
            .build()
        tags = [{'match': 'show', 'key': 'show', 'start_token': 0,
                 'entities': [{'key': 'show', 'match': 'show', 'data': [('show', 'Command')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False}]

        result_intent = intent.validate(tags, 1.0)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('Command') == "show"

    def test_basic_intent_with_alternate_names(self):
        intent = IntentBuilder("play television intent") \
            .require("PlayVerb", "Play Verb") \
            .require("Television Show", "series") \
            .build()
        tags = [{'match': 'play', 'key': 'play', 'start_token': 0,
                 'entities': [{'key': 'play', 'match': 'play', 'data': [('play', 'PlayVerb')], 'confidence': 1.0}],
                 'end_token': 0, 'from_context': False}, {'start_token': 1, 'entities': [
            {'key': 'the big bang theory', 'match': 'the big bang theory',
             'data': [('the big bang theory', 'Television Show')], 'confidence': 1.0}], 'confidence': 1.0,
                                                          'end_token': 4, 'match': 'the big bang theory',
                                                          'key': 'the big bang theory', 'from_context': False}]

        result_intent = intent.validate(tags, 0.95)
        assert result_intent.get('confidence') > 0.0
        assert result_intent.get('Play Verb') == 'play'
        assert result_intent.get('series') == "the big bang theory"

    def test_resolve_one_of(self):
        tags = [
            {
                "confidence": 1.0,
                "end_token": 1,
                "entities": [
                    {
                        "confidence": 1.0,
                        "data": [
                            [
                                "what is",
                                "skill_iot_controlINFORMATION_QUERY"
                            ]
                        ],
                        "key": "what is",
                        "match": "what is"
                    }
                ],
                "from_context": False,
                "key": "what is",
                "match": "what is",
                "start_token": 0
            },
            {
                "end_token": 3,
                "entities": [
                    {
                        "confidence": 1.0,
                        "data": [
                            [
                                "temperature",
                                "skill_weatherTemperature"
                            ],
                            [
                                "temperature",
                                "skill_iot_controlTEMPERATURE"
                            ]
                        ],
                        "key": "temperature",
                        "match": "temperature"
                    }
                ],
                "from_context": False,
                "key": "temperature",
                "match": "temperature",
                "start_token": 3
            },
            {
                "confidence": 1.0,
                "end_token": 7,
                "entities": [
                    {
                        "confidence": 1.0,
                        "data": [
                            [
                                "living room",
                                "skill_iot_controlENTITY"
                            ]
                        ],
                        "key": "living room",
                        "match": "living room"
                    }
                ],
                "from_context": False,
                "key": "living room",
                "match": "living room",
                "start_token": 6
            }
        ]

        at_least_one = [
            [
                "skill_iot_controlINFORMATION_QUERY"
            ],
            [
                "skill_iot_controlTEMPERATURE",
                "skill_iot_controlENTITY"
            ],
            [
                "skill_iot_controlTEMPERATURE"
            ]
        ]

        result = {
            "skill_iot_controlENTITY": [
                {
                    "confidence": 1.0,
                    "end_token": 7,
                    "entities": [
                        {
                            "confidence": 1.0,
                            "data": [
                                [
                                    "living room",
                                    "skill_iot_controlENTITY"
                                ]
                            ],
                            "key": "living room",
                            "match": "living room"
                        }
                    ],
                    "from_context": False,
                    "key": "living room",
                    "match": "living room",
                    "start_token": 6
                }
            ],
            "skill_iot_controlINFORMATION_QUERY": [
                {
                    "confidence": 1.0,
                    "end_token": 1,
                    "entities": [
                        {
                            "confidence": 1.0,
                            "data": [
                                [
                                    "what is",
                                    "skill_iot_controlINFORMATION_QUERY"
                                ]
                            ],
                            "key": "what is",
                            "match": "what is"
                        }
                    ],
                    "from_context": False,
                    "key": "what is",
                    "match": "what is",
                    "start_token": 0
                }
            ],
            "skill_iot_controlTEMPERATURE": [
                {
                    "end_token": 3,
                    "entities": [
                        {
                            "confidence": 1.0,
                            "data": [
                                [
                                    "temperature",
                                    "skill_weatherTemperature"
                                ],
                                [
                                    "temperature",
                                    "skill_iot_controlTEMPERATURE"
                                ]
                            ],
                            "key": "temperature",
                            "match": "temperature"
                        }
                    ],
                    "from_context": False,
                    "key": "temperature",
                    "match": "temperature",
                    "start_token": 3
                }
            ]
        }

        assert Intent._resolve_one_of(tags, at_least_one) == result
