from __future__ import annotations

"""Schema-driven PySide6 settings dialog; requires the optional gui extra."""

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget)

_SUPPORTED_TYPES = {"str", "int", "float", "bool", "choice"}


def _validate_schema(fields: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(fields, (str, bytes)) or not isinstance(fields, Sequence):
        raise TypeError("fields must be a sequence of field mappings")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping):
            raise TypeError(f"field {index} must be a mapping")
        spec = dict(field)
        key, kind = spec.get("key"), spec.get("type", "str")
        label = spec.get("label", key)
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError(f"field {index} has a missing or duplicate key")
        if kind not in _SUPPORTED_TYPES:
            raise ValueError(f"unsupported field type for {key!r}: {kind!r}")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"field {key!r} requires a non-empty label")
        if kind == "choice":
            choices = spec.get("choices")
            if (not isinstance(choices, Sequence) or isinstance(choices, (str, bytes))
                    or not choices or len(set(choices)) != len(choices)):
                raise ValueError(f"choice field {key!r} requires unique choices")
            spec["choices"] = list(choices)
        for bound in ("min", "max"):
            if bound in spec and kind not in {"int", "float"}:
                raise ValueError(f"{bound} is only valid for numeric field {key!r}")
        if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
            raise ValueError(f"minimum exceeds maximum for field {key!r}")
        seen.add(key)
        spec.update(key=key, type=kind, label=label)
        normalized.append(spec)
    return normalized


class SchemaSettingsDialog(QDialog):
    """Build a validated form from str/int/float/bool/choice field mappings."""

    def __init__(self, fields: Sequence[Mapping[str, Any]], parent: QWidget | None = None,
                 *, title: str = "Settings") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.fields = _validate_schema(fields)
        self.field_widgets: dict[str, QWidget] = {}
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        for spec in self.fields:
            widget = self._make_widget(spec)
            widget.setObjectName(f"setting_{spec['key']}")
            widget.setAccessibleName(spec["label"])
            if spec.get("description"):
                widget.setToolTip(str(spec["description"]))
            self.field_widgets[spec["key"]] = widget
            form.addRow(spec["label"], widget)
        self.error_label = QLabel("")
        self.error_label.setObjectName("settings_validation_error")
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("Validation errors")
        root.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    @staticmethod
    def _make_widget(spec: Mapping[str, Any]) -> QWidget:
        kind, default = spec["type"], spec.get("default")
        if kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(default))
            return widget
        if kind == "choice":
            widget = QComboBox()
            widget.addItems([str(choice) for choice in spec["choices"]])
            if default is not None:
                index = widget.findText(str(default))
                if index < 0:
                    raise ValueError(f"default is not a choice for {spec['key']!r}")
                widget.setCurrentIndex(index)
            return widget
        if kind == "int":
            widget = QSpinBox()
            widget.setRange(int(spec.get("min", -2147483647)), int(spec.get("max", 2147483647)))
            if default is not None:
                widget.setValue(int(default))
            return widget
        if kind == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(int(spec.get("decimals", 3)))
            widget.setRange(float(spec.get("min", -1e12)), float(spec.get("max", 1e12)))
            if default is not None:
                widget.setValue(float(default))
            return widget
        widget = QLineEdit("" if default is None else str(default))
        widget.setPlaceholderText(str(spec.get("placeholder", "")))
        return widget

    def values(self) -> dict[str, Any]:
        """Return current field values using their native Python types."""
        result: dict[str, Any] = {}
        for spec in self.fields:
            widget = self.field_widgets[spec["key"]]
            kind = spec["type"]
            if kind == "bool":
                value = widget.isChecked()
            elif kind == "choice":
                value = widget.currentText()
            elif kind in {"int", "float"}:
                value = widget.value()
            else:
                value = widget.text()
            result[spec["key"]] = value
        return result

    def validate(self) -> list[str]:
        """Return validation errors without closing the dialog."""
        current, errors = self.values(), []
        for spec in self.fields:
            key, value = spec["key"], current[spec["key"]]
            if spec.get("required") and spec["type"] == "str" and not value.strip():
                errors.append(f"{spec['label']} is required")
            if spec["type"] in {"int", "float"}:
                if "min" in spec and value < spec["min"]:
                    errors.append(f"{spec['label']} must be at least {spec['min']}")
                if "max" in spec and value > spec["max"]:
                    errors.append(f"{spec['label']} must be at most {spec['max']}")
            if spec["type"] == "choice" and value not in [str(v) for v in spec["choices"]]:
                errors.append(f"{spec['label']} must be one of the configured choices")
        return errors

    def accept(self) -> None:
        errors = self.validate()
        self.error_label.setText("\n".join(errors))
        if not errors:
            super().accept()
