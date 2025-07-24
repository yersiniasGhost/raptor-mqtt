from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import uuid
import aiomqtt
import asyncio
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from . import templates
from raptor_common.utils import LogManager
from raptor_common.config import MQTTConfig
from raptor_common.cloud.mqtt_comms import check_connection, send_message_and_wait_for_response
from raptor_common.config.mqtt_config import MQTTConfig, FORMAT_LINE_PROTOCOL

from pydantic import BaseModel


logger = LogManager().get_logger(__name__)
router = APIRouter(prefix="/messenger", tags=["messenger"])




class StockMessageRequest(BaseModel):
    raptor_mac: str
    template_id: str
    parameters: Optional[Dict[str, Any]] = {}


def get_available_raptors() -> List[dict]:
    return [
        {
            'name': 'Salinas Lab',
            'mac': 'c13e174a93d84da632e77dec67b6242a',
            'location': "Chase's Lab",
            "username": "chase-8c6466755ddacefa7cb5342367895ba8",
            "password": "pwd-bf24609be86885ed90220683396ead83",
        },
        {
            'name': 'PNW Lab',
            'mac': '8c6466755ddacefa7cb5342367895ba8',
            'location': "Friedrich Home",
            "username": "raptor-8c6466755ddacefa7cb5342367895ba8",
            "password": "bf24609be86885ed90220683396ead83",
        },
        {
            'name': 'Development Raptor',
            'mac': 'devel74a93d84da632e77dec67b6242a',
            'location': "Friedrich Home",
            "username": "raptor-c13e174a93d84da632e77dec67b6242a",
            "password": "c13e174a93d84da632e77dec67b6242a",
        },
    ]


def get_message_templates() -> List[dict]:
    return [
        {
            "id": 'reboot_system',
            'title': 'Reboot System',
            'action': 'reboot',
            'description': "Reboot the Raptor with options.",
            'button_class': 'btn-danger',
            'button_text': 'Reboot Raptor',
            'parameters': {
                'mode': {'type': 'radio-buttons', "title": "Reboot Mode", 'options': ["immediate", "delayed", "graceful"]},
                'delay': {'type': 'integer', "title": "Delay for reboot", "min": 0, "max": 1800, "step": 1, "default": 0},
                'force': {'type': 'checkbox', 'title': "Force reboot"},
                'graceful_timeout': {'type': 'integer', "title": "Timeout for graceful shutdown", "min": 1, "max": 120,
                                     "step": 1, "default": 30},
            }
        },
        {
            'id': 'firmware_update',
            'title': 'Firmware Update',
            'action': 'firmware_update',
            'description': 'Update device firmware',
            'button_class': 'btn-danger',
            'button_text': 'Update Firmware',
            'parameters': {
                'tag': {'type': 'text', "title": "Firmware version tag", "placeholder": "type here"},
                'force': {'type': 'checkbox', 'title': "Force update (true/false)", "default": False},
                'db_migrate': {'type': 'checkbox', 'title': "Run database migrator (not implemented yet)", "default": False},
                'restart_services': {'type': 'checkbox', 'title': "Restart Raptor services", 'default': True},
                "confirm_text": {'type': 'confirm-text', 'value': "Running firmware update, may take a minute or two."},
                'timeout': {'type': 'timeout', 'value': 120}
            }
        },
        {
            'id': 'system_status',
            'title': 'System Status',
            'action': 'system_status',
            'description': 'Get the firmware version, database schema state, etc.',
            'button_class': 'btn-normal',
            'button_text': 'Get State',
            'parameters': {
                'timeout': {'type': 'timeout', 'value': 30}
            }
        },
        {
            'id': 'taillog',
            'title': 'Tail Logs',
            'action': 'tail_log',
            'description': "Tail the log file for the selected process",
            'button_class': 'btn-normal',
            'button_text': 'Tail Log File',
            'parameters': {
                'lines': {'type': 'integer', "title": "Line count", "min": 20, "max": 1000, "step": 100, "default": 50},
                'process': {'type': "selection", "title": "Target", "options": [ "iot-controller",
                                                                                 "vmc-ui", "cmd-controller",
                                                                                 "reverse-tunnel", "network-watchdog"]}
            }
        },
        {
            'id': 'systemctl',
            'title': 'Service Management',
            'action': 'systemctl',
            'description': "Stop/Restart the Raptor's reverse SSH tunnel to AWS",
            'button_class': 'btn-warning',
            'button_text': 'Run systemctl',
            'parameters': {
                'cmd': {'type': 'radio-buttons', "title": "Command", 'options': ["status", "stop", "restart"]},
                'target': {'type': "selection", "title": "Target", "options": [ "iot-controller",
                                                                                "vmc-ui", "cmd-controller", "cellular-init",
                                                                                "reverse-tunnel", "network-watchdog"]}
            }
        },
        {
            'id': 'migrate',
            'title': 'Database migration',
            'action': 'database_migrator',
            'description': "Run the database migration using schema.sql",
            'button_class': 'btn-warning',
            'button_text': 'Run Migration',
            'parameters': {
                "hidden": {'type': 'hidden', 'title': ""}
            }
        },
        {
            "id": 'reverse_tunnel',
            'title': 'Reverse Tunnel',
            'action': 'create_reverse_tunnel',
            'description': "Start, stop and get status of the reverse tunnel",
            'button_class': 'btn-warning',
            'button_text': "Run Action",
            'parameters': {
                'action': {'type': 'selection', 'title': "Tunnel Operations",
                           'options': ['start', 'restart', 'stop', 'status']},
                'ui_port': {'type': 'text', 'title': 'AWS UI port', 'default': '2004'},
                'tunnel_port': {'type': 'text', 'title': 'AWS SSH tunnel port', 'default': '2024'},
                'server_user': {'type': 'text', 'title': 'AWS user', 'default': 'ubuntu'},
                'server_ip': {'type': 'text', 'title': 'AWS server IP', 'default': "54.226.49.65"}
            }
        },
        {
            "id": 'reconfigure',
            'title': 'Reconfigure Raptor',
            'action': 'reconfigure',
            'description': "Force the Raptor to request and update configuration",
            'button_class': 'btn-warning',
            'button_text': "Reconfigure",
            'parameters': {
                'api_url': {'type': 'text', 'title': 'CREM3 API URL', 'placeholder': 'http://3.80.169.34:3000'},
                'timeout': {'type': 'timeout', 'value': 60}
            }
        }

        #   {
        #     'id': 'inviewgw',
        #     'title': 'Inview Gateway Link',
        #     'action': 'inview_gw_link',
        #     'description': "Stop/Restart the Raptor's SSH connection to the Invie Gateway UI",
        #     'button_class': 'btn-normal',
        #     'button_text': 'Manage Link',
        #     'parameters': {
        #         'action': {'type': 'radio-buttons', "title": "Command", 'options': ["status", "connect", "disconnect"]},
        #         'aws': {'type': "checkbox", "title": "Use AWS"},
        #         'port': {'type': 'integer', "title": "AWS port", "min": 2000, "max": 2024, "step": 1, "default": 2004},
        #         'aws-target': {'type': 'text', "title": "AWS Credentials",  "value": "ubuntu@54.226.49.65"},
        #         'ssh-key': {"type": "selection", "title": "SSH key", "options": ["CREM3-API-03.pem"]}
        #     }
        # }
    ]


def get_mqtt_config() -> MQTTConfig:
    """Get MQTT broker configuration"""
    try:
        mqtt_config = MQTTConfig.get_mqtt_config()
        return mqtt_config

    except Exception as e:
        logger.error(f"Error getting MQTT config: {e}")
        return None


@router.get("/", response_class=HTMLResponse)
async def monitor(request: Request):
    """Main MQTT monitor and control interface"""
    try:
        # Get data for template
        raptors = get_available_raptors()
        message_templates = get_message_templates()
        mqtt_config = get_mqtt_config()

        logger.info(f"Rendering monitor page with {len(raptors)} raptors and {len(message_templates)} templates")

        return templates.TemplateResponse(
            "messenger.html",  # Changed from "messenger.html" to match the template
            {
                "request": request,
                "available_raptors": raptors,
                "message_templates": message_templates,
                "mqtt_broker_ip": mqtt_config.broker,
                "mqtt_broker_port": mqtt_config.port,
                "error": None
            }
        )

    except Exception as e:
        logger.error(f"Error in monitor route: {e}")
        return templates.TemplateResponse(
            "mqtt_control.html",
            {
                "request": request,
                "available_raptors": [],
                "message_templates": [],
                "mqtt_broker_ip": "localhost",
                "mqtt_broker_port": 1883,
                "error": str(e)
            }
        )


@router.post("/test-connection")
async def test_mqtt_connection():
    """Test MQTT broker connection"""
    try:
        mqtt_broker: MQTTConfig = get_mqtt_config()
        status = await check_connection(mqtt_broker, logger)
        # For now, return mock response - replace with actual test
        msg = "Connected to MQTT broker" if status else "Not connected to MQTT broker"
        return {"success": status, "message": msg}

    except Exception as e:
        logger.error(f"MQTT connection test failed: {e}")
        return {"success": False, "error": str(e)}



@router.post("/send-stock-message")
async def send_stock_message(request: StockMessageRequest):
    """Send a predefined stock message to a raptor device via MQTT"""
    try:
        logger.info(f"Sending stock message '{request.template_id}' to raptor {request.raptor_mac}")

        # Get the message template definition
        template = get_template_by_id(request.template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template '{request.template_id}' not found")

        # Validate parameters against template
        validated_params = validate_template_parameters(template, request.parameters)

        # Build the MQTT message
        message = build_mqtt_message(template, validated_params)
        action_id = message['action_id']

        # Get MQTT configuration
        mqtt_config = get_mqtt_config()

        # Determine the topic for this raptor
        command_topic = f"raptors/{request.raptor_mac}/messages"
        response_topic = f"raptors/{request.raptor_mac}/cmd_response"
        timeout = request.parameters.get('timeout', 30)

        # Send message and wait for response
        response = await send_message_and_wait_for_response(
            mqtt_config,
            command_topic,
            response_topic,
            message,
            action_id,
            timeout_seconds=timeout,
            logger=logger
        )
        if response:
            # Log the successful message send and response
            log_message_sent(request.raptor_mac, template['title'], message)
            log_message_response(request.raptor_mac, action_id, response)
            status = response.get('action_status', 'unknown')
            return {
                "success": status,
                "message": message,
                "response": response,
                "topic": command_topic,
                "response_topic": response_topic,
                "timestamp": datetime.now().isoformat()
            }
        else:
            # Message sent but no response received
            log_message_sent(request.raptor_mac, template['title'], message)

            return {
                "success": False,
                "message": message,
                "response": {"error": "No response received within timeout period"},
                "topic": command_topic,
                "response_topic": response_topic,
                "timestamp": datetime.now().isoformat(),
                "warning": "Command sent but no response received"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending stock message: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/raptor-status/{mac}")
async def get_raptor_status(mac: str):
    """Get status of specific raptor device"""
    try:
        # This would query your database or MQTT last-will messages
        # For now, return mock data - replace with actual status lookup

        raptors = get_available_raptors()
        raptor = next((r for r in raptors if r['mac'] == mac), None)

        if not raptor:
            raise HTTPException(status_code=404, detail="Raptor not found")

        return {
            "online": raptor.get('online', False),
            "last_seen": raptor.get('last_seen', 'Never'),
            "uptime": "2 days, 14 hours",  # Mock data
            "version": "v2.1.0"  # Mock data
        }

    except Exception as e:
        logger.error(f"Error getting raptor status for {mac}: {e}")
        return {"online": False, "last_seen": "Unknown", "error": str(e)}


def get_template_by_id(template_id: str) -> Optional[Dict[str, Any]]:
    """Get message template by ID - should match get_message_templates() from the main route"""
    templates = get_message_templates()  # Reuse the same function from your main route
    return next((t for t in templates if t['id'] == template_id), None)


def validate_template_parameters(template: Dict[str, Any], provided_params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean parameters according to template definition"""
    validated = {}
    template_params = template.get('parameters', {})

    for param_name, param_def in template_params.items():
        param_type = param_def.get('type', 'text')
        provided_value = provided_params.get(param_name)

        if param_type == 'selection':
            # Validate selection is in allowed options
            options = param_def.get('options', [])
            if provided_value and provided_value in options:
                validated[param_name] = provided_value
            elif options:
                validated[param_name] = options[0]  # Default to first option

        elif param_type == 'checkbox':
            # Convert to boolean
            validated[param_name] = bool(provided_value)

        elif param_type == 'radio-buttons':
            # Validate radio selection
            options = param_def.get('options', [])
            if provided_value and provided_value in options:
                validated[param_name] = provided_value
            elif options:
                validated[param_name] = options[0]  # Default to first option
        elif param_type == 'integer':
            # Convert and validate number
            try:
                if provided_value is not None:
                    num_value = int(provided_value)
                    min_val = param_def.get('min')
                    max_val = param_def.get('max')

                    if min_val is not None and num_value < min_val:
                        num_value = min_val
                    if max_val is not None and num_value > max_val:
                        num_value = max_val

                    validated[param_name] = num_value
            except (ValueError, TypeError):
                logger.warning(f"Invalid number value for {param_name}: {provided_value}")

        elif param_type == 'number':
            # Convert and validate number
            try:
                if provided_value is not None:
                    num_value = float(provided_value)
                    min_val = param_def.get('min')
                    max_val = param_def.get('max')

                    if min_val is not None and num_value < min_val:
                        num_value = min_val
                    if max_val is not None and num_value > max_val:
                        num_value = max_val

                    # Convert back to int if step is 1
                    if param_def.get('step', 1) == 1:
                        validated[param_name] = int(num_value)
                    else:
                        validated[param_name] = num_value
            except (ValueError, TypeError):
                logger.warning(f"Invalid number value for {param_name}: {provided_value}")

        elif param_type == 'text':
            # String parameter
            if provided_value:
                validated[param_name] = str(provided_value).strip()

    logger.debug(f"Validated parameters: {validated}")
    return validated


def build_mqtt_message(template: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Build the MQTT message payload"""
    message = {
        "action": template['action'],
        "params": parameters,
        "action_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "source": "raptor-mqtt-ui"
    }
    return message



def log_message_sent(raptor_mac: str, template_title: str, message: Dict[str, Any]):
    """Log the message send event (could also store in database)"""
    logger.info(f"MQTT message sent - Raptor: {raptor_mac}, Template: {template_title}, "
                f"Action: {message.get('action')}, ID: {message.get('action_id')}")

    # Optional: Store in database for message history
    try:
        # db = DatabaseManager()
        # db.log_mqtt_message_sent(raptor_mac, template_title, message)
        pass
    except Exception as e:
        logger.warning(f"Failed to log message to database: {e}")


def log_message_response(raptor_mac: str, action_id: str, response: Dict[str, Any]):
    """Log the response received"""
    status = response.get('action_status', 'unknown')
    logger.info(f"MQTT response received - Raptor: {raptor_mac}, ID: {action_id}, Status: {status}")

    # Optional: Store response in database
    try:
        # db = DatabaseManager()
        # db.log_mqtt_message_response(raptor_mac, action_id, response)
        pass
    except Exception as e:
        logger.warning(f"Failed to log response to database: {e}")
