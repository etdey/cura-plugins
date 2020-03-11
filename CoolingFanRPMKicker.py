# Cura PostProcessingPlugin
# Author:   Eric Dey
# Date:     March 08, 2020
# Modified: March 11, 2020

# Description: This plugin modifies the part cooling fan speed commands
#              to provide a start-up "kicker" to help the fan start spinning.
# 
# The kicker is an additional GCode command to spin the fan fast enough to 
# cause it to start turning followed by the slower fan speed requested in
# the original GCode. The kicker is only provided when attempting to speed up
# from OFF or an unsustainable slower speed to a speed that is still below
# the startup threshold that will make the fan start spinning.
#

from ..Script import Script

import re


class CoolingFanRPMKicker(Script):

    def __init__(self):
        super().__init__()
        
        self.settings = {
            "kickerSpeed" : 255.0,
            "kickerWaitTimeMs" : 100,
            "minSustainableSpeed" : 27.0,
            "minStartupSpeed" : 100.0,
            "enforceMinSpeed" : None,
            "useFanIndex" : None,
            "fanIndex" : 0,
        }
    

    def getSettingDataString(self):
        return("""{
            "name":"Cooling Fan RPM Kicker",
            "key":"CoolingFanRPMKicker",
            "metadata": {},
            "version": 2,
            "settings":
            {
                "scriptEnabled":
                {
                    "label": "Enable",
                    "description": "Enable GCode modification for providing a startup 'kicker' to the cooling fan.",
                    "type": "bool",
                    "default_value": false
                },
                "kickerSpeed":
                {
                    "label": "Kicker Speed",
                    "description": "Target speed to set in ordert to kick fan into motion",
                    "type": "float",
                    "default_value": %0.0f
                },
                "kickerWaitTimeMs":
                {
                    "label": "Delay After Kick (ms)",
                    "description": "The length of time to wait to let the speed kick take effect",
                    "type": "int",
                    "default_value": %d
                },
                "minSustainableSpeed":
                {
                    "label": "Minimum Sustainable Fan Speed",
                    "description": "Speed below which the fan will not continue to spin",
                    "type": "float",
                    "default_value": %0.0f
                },
                "minStartupSpeed":
                {
                    "label": "Minimum Startup Speed",
                    "description": "Lowest speed at which fan will start normally without a kick",
                    "type": "float",
                    "default_value": %0.0f
                },
                "enforceMinSpeed":
                {
                    "label": "Enforce Sustainable Speed",
                    "description": "Force any slower fan speeds to be at least the minimum sustainable value",
                    "type": "bool",
                    "default_value": false
                },
                "useFanIndex":
                {
                    "label": "Use Fan Index",
                    "description": "Specify a fan index for the 'M106 P<num>' parameter",
                    "type": "bool",
                    "default_value": false
                },
                "fanIndex ":
                {
                    "label": "Fan Index",
                    "description": "The 'M106 P<num>' parameter value to look for an use in the GCode",
                    "type": "int",
                    "default_value": %d
                }
                
            }
        }""" % (
                self.settings["kickerSpeed"],
                self.settings["kickerWaitTimeMs"],
                self.settings["minSustainableSpeed"],
                self.settings["minStartupSpeed"],
                self.settings["fanIndex"]
            )
        )
    
    
    def execute(self, data):
        if not self.getSettingValueByKey("scriptEnabled"):
            return(data)
        
        # Get operational settings from user
        for name in self.settings.keys():
            self.settings[name] = self.getSettingValueByKey(name)
        
        # Create GCode RE match pattern and replacement format string
        if self.settings["useFanIndex"] is False:
            reFanGcode = re.compile("""^[Mm]106 +S([0-9.]+)(.*)$""")
            formatFanSpeedGcode = "M106 S%0.0f%s"
            fanSpeedKickerGcode = "M106 S%0.0f" % (self.settings["kickerSpeed"])
        else:
            reFanGcode = re.compile("""^M106 +P0*%d +S([0-9.]+)(.*)$""" % (self.settings["fanIndex"]))
            formatFanSpeedGcode = "M106 P%d" % (self.settings["fanIndex"]) + "S%0.0f%s"
            fanSpeedKickerGcode = "M106 P%d S%0.0f" % (self.settings["fanIndex"], self.settings["kickerSpeed"])
        
        previousFanSpeed = 0.0   # assume fan is off at start
        
        layerNum = 0
        for layer in data:
            lines = layer.split("\n")
            lineNum = 0   # line number within this layer
            
            for line in lines:
                # skip to next line if this isn't an "M" command
                if not line.startswith("M"):
                    lineNum += 1
                    continue
                
                # Attempt to match fan speed GCode command
                m = reFanGcode.match(line)
                if m is None:
                    lineNum += 1
                    continue
                
                try:
                    newFanSpeed = float(m.group(1))
                    lineEnding = m.group(2)
                except ValueError:
                    newFanSpeed = 0
                    lineEnding = ""
                
                # Ensure speed stays in allowable range
                if newFanSpeed < 0.001:
                    newFanSpeed = 0.0
                if newFanSpeed > 255.0:
                    newFanSpeed = 255.0
                
                # Enforce minimum sustainable speed
                if newFanSpeed > 0 and newFanSpeed < self.settings["minSustainableSpeed"] and self.settings["enforceMinSpeed"] is True:
                    lineEnding += "; enforcing minimum speed since %s is too low" % (newFanSpeed)
                    newFanSpeed = self.settings["minSustainableSpeed"]
                    lines[lineNum] = formatFanSpeedGcode % (newFanSpeed, lineEnding)
                
                # If changing to a fan speed greater than min startup, 
                # there's no need for a kicker.
                kickerNeeded = True
                if newFanSpeed == 0:
                    kickerNeeded = False
                elif newFanSpeed >= self.settings["minStartupSpeed"]:
                    kickerNeeded = False
                elif newFanSpeed > previousFanSpeed and previousFanSpeed >= self.settings["minSustainableSpeed"]:
                    kickerNeeded = False
                elif newFanSpeed < previousFanSpeed:
                    kickerNeeded = False

                # Go to next line of GCode if kicker not needed
                if  kickerNeeded is False:
                    previousFanSpeed = newFanSpeed
                    lineNum += 1
                    continue
                
                # Insert new GCode lines by using a newline in the existing string
                # and update the current line list entry of GCode
                newLine = ";Fan speed kicker for change from %s -> %s" % (previousFanSpeed, newFanSpeed)
                newLine += "\nM400 ; finish moves before adjusting fan"
                newLine += "\n" + fanSpeedKickerGcode
                newLine += "\n" + "G4 P%d ; wait for kick to take effect" % (self.settings["kickerWaitTimeMs"])
                newLine += "\n" + formatFanSpeedGcode % (newFanSpeed, lineEnding)
                
                lines[lineNum] = newLine  # replace the line of GCode
                data[layerNum] = "\n".join(lines)  # replace the layer text
                
                previousFanSpeed = newFanSpeed
                lineNum += 1
            
            layerNum += 1
        
        return(data)
