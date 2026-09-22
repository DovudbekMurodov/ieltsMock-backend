from rest_framework import serializers


class StartAttemptSerializer(serializers.Serializer):
    testId = serializers.SlugField()


class AnswerEntrySerializer(serializers.Serializer):
    questionId = serializers.IntegerField()
    value = serializers.CharField(allow_blank=True, required=False, max_length=2000)
    optionId = serializers.IntegerField(required=False, allow_null=True)
    timeSpentMs = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class SaveAnswersSerializer(serializers.Serializer):
    answers = AnswerEntrySerializer(many=True)


class AttemptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    token = serializers.UUIDField()
    testId = serializers.SlugField(source="test.slug")
    skill = serializers.CharField(source="test.skill")
    status = serializers.CharField()
    startedAt = serializers.DateTimeField(source="started_at")
    expiresAt = serializers.DateTimeField(source="expires_at")
    secondsRemaining = serializers.IntegerField(source="seconds_remaining")


class AttemptResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    rawScore = serializers.IntegerField(source="raw_score")
    rawTotal = serializers.IntegerField(source="raw_total")
    percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    durationSeconds = serializers.IntegerField(source="duration_seconds")


class ClaimSerializer(serializers.Serializer):
    claimed = serializers.IntegerField()
