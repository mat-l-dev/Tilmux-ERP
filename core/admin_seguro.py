"""Opciones comunes para documentos con efectos contables."""


class SoloConsultaContable:
    """Evita guardar documentos sin pasar por sus servicios contables."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
