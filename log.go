package main

import (
	"fmt"
	"log"
	"os"
	"strings"
)

var (
	Debug   *log.Logger
	Info    *log.Logger
	Warning *log.Logger
	Error   *log.Logger
)

func SetupLogging(cfg *Config) {
	flags := log.Ldate | log.Ltime | log.Lmsgprefix
	prefix := func(lvl string) string { return fmt.Sprintf("%-7s | ", lvl) }

	Info = log.New(os.Stderr, prefix("INFO"), flags)
	Warning = log.New(os.Stderr, prefix("WARN"), flags)
	Error = log.New(os.Stderr, prefix("ERROR"), flags)
	Debug = log.New(os.Stderr, prefix("DEBUG"), flags)

	level := strings.ToUpper(cfg.LogLevel)
	if level == "WARNING" || level == "WARN" {
		Debug.SetOutput(nil)
		Info.SetOutput(nil)
	} else if level == "ERROR" {
		Debug.SetOutput(nil)
		Info.SetOutput(nil)
		Warning.SetOutput(nil)
	}
}
