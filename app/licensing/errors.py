from __future__ import annotations


class LicensingError(RuntimeError):
    pass


class DeviceFingerprintError(LicensingError):
    pass


class LicenseValidationError(LicensingError):
    pass


class LicenseStorageError(LicensingError):
    pass


class LicenseApiError(LicensingError):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        trace_id: str = "",
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "SERVER_TEMPORARILY_UNAVAILABLE")
        self.message = str(message or "License service request failed")
        self.retryable = bool(retryable)
        self.trace_id = str(trace_id or "")
        self.status_code = status_code


ERROR_MESSAGES_ZH = {
    "TRIAL_EXPIRED": "7天免费试用已结束，激活后可继续录制。",
    "TRIAL_ALREADY_USED": "该设备已使用过免费试用，请输入激活码继续使用录制功能。",
    "TRIAL_CONVERTED": "该设备已使用过免费试用，请输入激活码继续使用录制功能。",
    "TRIAL_DISABLED": "当前设备无法继续使用免费试用，请联系管理员。",
    "TRIAL_DEVICE_MISMATCH": "免费试用与当前设备不匹配。",
    "TRIAL_TEMPORARILY_UNAVAILABLE": "暂时无法开启免费试用，请检查网络后重试。",
    "LICENSE_NOT_FOUND": "激活码不存在，请检查后重新输入。",
    "LICENSE_ALREADY_BOUND": "该激活码已绑定其他电脑，请先在原电脑解绑。",
    "LICENSE_EXPIRED": "该授权已过期。",
    "LICENSE_DISABLED": "该授权已被停用，请联系管理员。",
    "LICENSE_REVOKED": "该授权已被撤销，请联系管理员。",
    "DEVICE_MISMATCH": "授权与当前电脑不匹配。",
    "DEVICE_DISABLED": "当前设备授权已被停用，请联系管理员。",
    "INVALID_CREDENTIAL": "本机授权凭据无效，请重新激活。",
    "INVALID_REQUEST": "授权请求格式不正确，请检查后重试。",
    "DUPLICATE_REQUEST": "请求标识冲突，请重新操作。",
    "CLIENT_VERSION_UNSUPPORTED": "当前客户端版本不受支持，请升级后重试。",
    "RATE_LIMITED": "操作过于频繁，请稍后重试。",
    "SERVER_TEMPORARILY_UNAVAILABLE": "授权服务器暂时不可用，请稍后重试。",
}


def localized_error(error: LicenseApiError) -> str:
    return ERROR_MESSAGES_ZH.get(error.code, error.message or "授权操作失败，请稍后重试。")
