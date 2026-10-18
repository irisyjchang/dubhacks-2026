"""Safe, actionable errors shared by the worker and upload server."""


class CoachingServiceError(RuntimeError):
    def __init__(self,status=None,*,timeout=False):
        self.code='nvidia_timeout' if timeout else 'nvidia_credentials' if status in {401,403} else 'nvidia_unavailable'
        self.retryable=timeout or status==429 or status is not None and status>=500
        if timeout:
            message='NVIDIA coaching timed out. Your video and tracked poses are saved; retry report generation.'
        elif status in {401,403}:
            message='NVIDIA rejected the API key or model access. Check the key configured for this upload.'
        else:
            message=f'NVIDIA coaching returned HTTP {status} after recovery attempts. Your video and tracked poses are saved.'
        super().__init__(message)


class ProcessingFailure(RuntimeError):
    def __init__(self,message,code='processing_failed',retryable=False):
        super().__init__(message)
        self.code=code
        self.retryable=retryable
